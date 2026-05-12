# Eval data

Evaluation inputs for `scripts/eval_persona.py`. These are **not** training
data — training data lives in `../sft/` and `../dpo/`.

## Files

```
data/eval/
├── README.md
└── probes_v1.jsonl     one drift-probe per line (JSONL)
```

## Probe schema

One JSON object per line. Fields:

| field          | required | notes |
|---|---|---|
| `probe_id`     | yes      | stable slug, e.g. `lily-id-01`. Used as the output key and in reports |
| `probe_type`   | yes      | one of `identity / emotion-mirror / crisis / code-switch / boundary / tone / long-context / other` (same enum as `schemas/dpo_alpaca.schema.json`) |
| `persona_id`   | yes      | matches a file under `personas/`: `personas/<persona_id>_<language>.md` |
| `language`     | yes      | ISO 639-1 |
| `instruction`  | yes      | the user turn |
| `history`      | no       | `[[user, assistant], ...]`, oldest first — same shape as SFT/DPO records |
| `hard_rejects` | no       | case-insensitive substrings that cost the probe an automatic penalty on the primary dimension if they appear in the candidate reply |
| `notes`        | no       | human-only; ignored by the pipeline |

## How probes relate to DPO data

A good probe is the `instruction` side of a preference pair you would gladly
add to `../dpo/*.json`. The `rejected` response for a DPO pair often contains
exactly the phrases you'd list in `hard_rejects` for the matching probe
(e.g. "As an AI language model...").

Probes and DPO data should co-evolve:

1. Observe a real drift in a training run.
2. Write a probe capturing the failure.
3. Write a DPO pair fixing it.
4. Re-run eval, confirm the probe score goes up.

## Adding new probes

```
# Append a line:
echo '{"probe_id":"lily-boundary-03", ...}' >> data/eval/probes_v1.jsonl

# Smoke-run pipeline against it:
make eval-dry
```

Validation happens at load time via pydantic; malformed lines fail loudly.

## Versioning

When a breaking probe-set change happens (removing probes, renaming ids, changing
semantics of a probe_type), bump to `probes_v2.jsonl` — never rewrite history in
`probes_v1.jsonl`. Otherwise reports from old runs become uncomparable to new ones.
