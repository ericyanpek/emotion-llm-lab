# Persona eval pipeline

Evaluates a candidate model's adherence to a persona through drift probes +
LLM-as-judge scoring. Produces a Markdown summary per run.

Entry point: [`scripts/eval_persona.py`](../eval_persona.py) — a `typer` CLI.

## Quick start

```bash
# 1) Dry-run the whole pipeline with zero network / zero API keys.
make eval-dry

# 2) Real eval: vLLM on localhost:8000 (via `make tunnel`), judged by Claude.
export ANTHROPIC_API_KEY=...   # or put it in .env
uv run python scripts/eval_persona.py run \
    --probes data/eval/probes_v1.jsonl \
    --candidate-backend  openai \
    --candidate-model    Qwen/Qwen3-8B \
    --candidate-base-url http://localhost:8000/v1 \
    --judge-backend      anthropic
```

## Subcommands

```bash
# Validate probe JSONL against data/eval/probe.schema.json
uv run python scripts/eval_persona.py validate --probes data/eval/probes_v1.jsonl

# Judge calibration against committed DPO preference pairs
# (does the judge reliably prefer `chosen` over `rejected`?)
uv run python scripts/eval_persona.py calibrate \
    --dpo data/dpo/emotion_dpo_tiny.json \
    --dpo data/dpo/emotion_dpo_tiny_zh.json \
    --judge-backend anthropic

# List probes (optional filters)
uv run python scripts/eval_persona.py list \
    --probes data/eval/probes_v1.jsonl --language en

# Run tests
uv run pytest scripts/eval/tests/ -q
```

```
scripts/
├── eval_persona.py          CLI (typer)
└── eval/
    ├── probes.py            JSONL loader + persona system-prompt extractor
    ├── candidates.py        OpenAI-compatible + stub candidate clients
    ├── judges.py            Claude + OpenAI + stub judges
    ├── rubric.py            rubric model + judge prompt template
    ├── report.py            aggregate + render (JSONL / JSON / Markdown)
    ├── calibrate.py         judge calibration against committed DPO pairs
    └── tests/               pytest unit tests for the rubric math + loaders

configs/eval/rubric_v1.yaml  weights + penalties
data/eval/probes_v1.jsonl    seed probe set
data/eval/probe.schema.json  JSON Schema mirror of the Probe pydantic model
outputs/eval/<run_id>/       per-run eval artifacts (gitignored)
outputs/eval/calibration/<run_id>/   per-run calibration artifacts (gitignored)
```

## Design notes

- **Same protocol for candidate and OpenAI judge**. vLLM serves an OpenAI
  endpoint, so a single `OpenAI(client)` path works for local inference,
  hosted OpenAI, and hosted baselines. Swap backends by changing `--candidate-backend`.
- **Four rubric dimensions map 1:1 to persona doc sections** (`voice`,
  `emotional_register`, `identity`, `boundaries`). Judge is asked for each on
  a 1-5 scale with a short rationale, JSON-only, to keep parsing robust.
- **Hard-reject substrings are deterministic**. If `"as an ai language model"`
  appears, we don't trust the judge to catch it — we subtract a fixed penalty
  from the primary dimension. Prevents a lenient judge from hiding known failures.
- **`probe_type` shares the enum with the DPO schema**. A drift probe and a
  DPO preference pair that target the same failure should be tagged identically,
  so you can cross-reference them when a run regresses.
- **Stub backends everywhere**. Both the candidate and the judge have heuristic
  stub implementations, enabling `--dry-run` that needs no network and no API
  keys. This is what CI runs.

## Output

Each run writes to `outputs/eval/<run_id>/`:

- `results.jsonl` — one line per probe: probe + reply + verdict + weighted score
- `summary.json`  — machine-readable aggregates (overall, by language, by probe_type)
- `summary.md`    — human-readable report including the bottom-5 "low scorers"

`<run_id>` is `YYYYMMDDTHHMMSSZ-<hash4>`. Outputs are gitignored — publish
relevant reports as PR comments or ship to S3.

## Adding a new persona

1. Drop `personas/<persona_id>_<language>.md` following `_template.md`.
2. Append probes to `data/eval/probes_v1.jsonl` referencing the new `persona_id`.
3. Re-run eval. No code changes required.

## Adding a new judge backend

Implement the `JudgeClient` protocol in `judges.py` (one `score()` method returning a
`JudgeVerdict`), register it in `make_judge`, and it's usable via `--judge-backend`.
Same pattern for new candidate backends in `candidates.py`.
