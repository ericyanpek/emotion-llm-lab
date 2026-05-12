# ADR-0011: Eval pipeline — 4-dimension rubric, LLM-as-judge, and deterministic drift-probe guardrails

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** project PoC author

## Context

The SFT smoke run produced a 167 MB LoRA adapter, but "loss went down" tells
us nothing about whether the model sounds like Lily or whether it breaks
character under AI-probe pressure. We need a repeatable way to answer:

1. Does the candidate model match the persona's **voice**?
2. Does it hold **emotional register** (mirror, stay with feelings) instead
   of jumping to checklists?
3. Does it keep **identity** under pressure ("are you a bot?", "pretend to
   be my boyfriend") without falling into templatey disclaimers?
4. Does it honor **boundaries** (medical, legal, role-play) in character?

Constraints:

- **Deterministic where it can be.** Some failure modes are literal strings
  ("As an AI language model...") — we should not rely on a judge model's
  mood to flag them
- **Runnable offline.** We iterate on persona docs and DPO data on the
  Mac with no GPU and no API keys; CI shouldn't need them either
- **Same vocabulary as DPO data.** A probe that catches a drift should be
  cross-referenceable to the DPO preference pair that fixes it
- **Protocol parity with vLLM.** Our production inference server speaks the
  OpenAI chat-completions protocol (`--enable-lora`), so the eval client
  should use the same protocol against any backend
- **Judge should be strong on instruction following.** Multi-dimensional
  rubric with a JSON-only output format is the task that makes weak judges
  drift

## Decision

Four coupled choices:

### Choice 1 — Rubric is 4 dimensions, 1-5 integer, uniform weights by default

Dimensions: `voice`, `emotional_register`, `identity`, `boundaries`. Each
scored 1-5 by the judge with one short rationale sentence. Weighted mean
aggregates to a single weighted score per probe; weights are configurable
via `configs/eval/rubric_v1.yaml` but default to uniform.

The dimensions map 1:1 to section headings in `personas/_template.md`,
so persona authors, data labelers, and the judge all use the same words.

### Choice 2 — Deterministic hard-reject substrings complement the judge

Every probe can declare `hard_rejects`: a list of case-insensitive
substrings that, if present in the candidate reply, subtract a fixed
penalty (default 2.0) from the **primary dimension** for that probe type
(e.g. `identity` for an `identity` probe). This runs *after* the judge
scores, so:

- A lenient judge can't hide the exact failure patterns we've already
  seen break production ("As an AI language model...")
- We never need a judge call at all to know certain things are wrong
- The judge's score is still informative when no hard-reject fires

The primary-dimension map lives in `scripts/eval/rubric.py`
(`PROBE_PRIMARY_DIMENSIONS`).

### Choice 3 — Candidate and judge both have `stub` backends

The eval pipeline exposes three candidate backends (`stub`, `openai`) and
three judge backends (`stub`, `anthropic`, `openai`). The stubs are
deterministic: the stub candidate returns canned replies keyed by
`probe_id` including intentionally bad ones; the stub judge uses a small
set of regex heuristics. With `--dry-run`, both default to stubs and the
whole pipeline runs in under a second on a Mac with no API keys.

This is what `make eval-dry` runs and what CI will run. Real evaluation
uses `--candidate-backend openai --candidate-base-url http://localhost:8000/v1`
(vLLM) and `--judge-backend anthropic` (Claude).

### Choice 4 — `probe_type` shares the enum with the DPO schema

The `drift_probe` enum in `schemas/dpo_alpaca.schema.json` (`identity`,
`emotion-mirror`, `crisis`, `code-switch`, `boundary`, `tone`,
`long-context`, `other`) is reused verbatim as `probe_type` in eval.
A DPO pair and an eval probe that target the same failure MUST use the
same tag. This lets us answer, after a run regresses: "which DPO pair was
supposed to prevent this, and did it ship?"

Default judge is Claude (`claude-3-5-sonnet-latest`). OpenAI is available
as a cross-check / tiebreaker, not as the primary.

## Consequences

Good:

- **Iteration is cheap.** Add a probe, run `make eval-dry` locally in
  seconds, review the JSONL + Markdown diff, commit. No GPU, no API keys
- **CI gets a real pipeline smoke.** The stub heuristics score known-bad
  canned replies correctly, so the pipeline's scoring math (weighted
  aggregation, hard-reject penalty, grouping by language / probe_type)
  has continuous coverage
- **Judge drift is detectable.** When we do run Claude vs GPT-4o on the
  same probe set, divergences in score are a signal about the judge, not
  just the candidate
- **Reports are shippable.** `outputs/eval/<run_id>/summary.md` is PR-comment
  ready; `summary.json` is machine-readable for a future dashboard
- **Persona authors and DPO labelers share a vocabulary.** No more "this is
  a drift" / "no, this is a vibe issue" arguments — rubric dimensions are
  named and defined in one place

Bad / watch-outs:

- **Judge cost is real when we scale probes.** 11 probes × 2 judges × N
  model variants multiplies fast. The plan is: use stub in the inner
  loop, call Claude only on the candidates that already pass stub +
  hard-rejects
- **Stub judge is hand-tuned heuristics.** It will score some real replies
  wrong. It's a *pipeline* test, not a *quality* test. Never ship a model
  decision based on stub scores alone
- **`hard_rejects` is substring-matched**, not semantic. A rewording
  ("I'm just a language model") will slip past until we add it. This is a
  feature (deterministic, no false positives) but requires maintenance
- **Rubric weights are hard to re-tune later.** If we change a weight mid-
  project, old runs become uncomparable. `rubric_v1.yaml` is a pinned
  baseline; a new rubric version (v2) would mean a new file, not a rewrite
- **JSON parsing failures from the judge are possible.** We fall back to
  neutral scores (3/3/3/3) with a `parse_failed` flag, so a weird judge
  output doesn't crash the run; the `parse_failure_rate` aggregate is in
  the summary to make it visible

## Alternatives considered

| Option | Why rejected |
|---|---|
| Classifier-based drift detection (embedding similarity to persona) | Fast but blind to subtleties — a checklist-style reply can be textually close to a mirroring reply. Keep as a future additive signal, not the primary |
| Pairwise A/B judging (`is A more X than B?`) | Better for ranking candidates, worse for absolute persona fidelity. We want "how Lily is this reply on its own", which is a 1-5 rubric not a comparison |
| Only LLM-as-judge, no hard-reject step | Post-mortem on the DPO training set showed judges sometimes scored "As an AI language model..." as 3/5 on identity with a polite rationale. Hard-rejects prevent this class of blind spot |
| Only hard-reject rules, no LLM judge | Scales poorly; can't evaluate "does this reply feel like Lily" — only "does it say a forbidden phrase" |
| 7+ rubric dimensions (warmth, specificity, brevity, etc.) | Longer rubrics make judges' scores more noisy and correlate the dimensions we care about. 4 dimensions is enough to slice drift and maps to the persona doc's structure |
| Hosted eval service (Braintrust, Langsmith, etc.) | Overkill for a PoC; couples CI to a third-party account; stubs in-process are simpler and version-control as code |

## References

- Persona rubric structure: `personas/_template.md`
- Drift-probe enum: `schemas/dpo_alpaca.schema.json` → `drift_probe`
- Pipeline code: `scripts/eval/` + `scripts/eval_persona.py`
- Seed probes: `data/eval/probes_v1.jsonl`
- Rubric config: `configs/eval/rubric_v1.yaml`
- Related: ADR-0006 (SFT → DPO, which this evaluates); ADR-0002 (vLLM, whose
  OpenAI-compat endpoint is the candidate protocol)
