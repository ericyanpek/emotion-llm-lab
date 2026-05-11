# Data directory

Training data that LLaMA-Factory consumes. Layout:

```
data/
├── README.md             this file
├── dataset_info.json     LLaMA-Factory manifest — list every dataset the training YAMLs reference
├── sft/                  Alpaca-style SFT records (one .json per dataset)
│   └── emotion_sft_tiny.json
└── dpo/                  Alpaca-style pairwise preference records (one .json per dataset)
    └── emotion_dpo_tiny.json
```

## What belongs here vs S3

| Scale | Location | Why |
|---|---|---|
| "tiny" samples (≤ a few dozen records) | this repo, committed | pipeline smoke tests, onboarding, PR review |
| "v1+" real datasets (500–5000 records) | S3 (`s3://emotion-companion-dev-artifacts-.../sft/...`) | too big for git; may contain PII-sensitive content; canonical source is the synth run that produced them |
| checkpoints, adapters | S3 (`.../adapters/...`) | even larger; produced by this repo, not committed |

When a real dataset lands on S3, add an entry to `dataset_info.json` with
`file_name: s3://...` and reference it from the training YAML. LLaMA-Factory
will use `s3fs` to read it directly — no pre-download step needed.

## Dataset naming convention

```
emotion_<stage>_<language>_<version>
  stage:    sft | dpo | kto
  language: en | zh | es | ja | fr | ... (ISO 639-1) or `multi` for a mix
  version:  tiny | v1 | v2 ...
```

Examples:
- `emotion_sft_tiny`             smoke test set
- `emotion_sft_en_v1`            first real English SFT batch
- `emotion_dpo_multi_v1`         multilingual DPO mix
- `emotion_kto_en_v1`            single-label variant (if we switch algorithms)

## Schema contract

All records must validate against the schemas in [`../schemas/`](../schemas/):

- SFT → `schemas/sft_alpaca.schema.json`
- DPO → `schemas/dpo_alpaca.schema.json`

Every SFT record **requires a non-empty `system` field** (our discipline,
stricter than LLaMA-Factory's own expectations). Every DPO record requires
`chosen`, `rejected`, **and** `system`. The `persona_id` / `language` /
`drift_probe` metadata fields are optional at training time but required
for eval slicing — keep them populated.

## Upstream: how these files get produced

For "tiny" bootstrapping samples (this batch): written by hand, reviewed
like code in PRs.

For "v1+" data at scale: produced by synth scripts in
[`ollama-gpu-host-aws`](https://github.com/ericyanpek/ollama-gpu-host-aws)
running Gemma 4 / Qwen-Max / other teacher models on a short-lived GPU
instance. Synth scripts write directly in the schemas above, validate
against the JSON Schema before writing to S3, and never land in this repo
except through `dataset_info.json` references.

## How to validate locally

```bash
uv run python - <<'PY'
import json
from jsonschema import Draft202012Validator
for stage, path in [("sft", "data/sft/emotion_sft_tiny.json"),
                    ("dpo", "data/dpo/emotion_dpo_tiny.json")]:
    schema = json.load(open(f"schemas/{stage}_alpaca.schema.json"))
    data   = json.load(open(path))
    errors = list(Draft202012Validator(schema).iter_errors(data))
    if errors:
        for e in errors: print(f"[{stage}] {list(e.absolute_path)}: {e.message}")
        raise SystemExit(1)
print("all datasets valid")
PY
```

A future `make validate-data` target will wrap this. Not wired yet in this
batch.
