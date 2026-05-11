# Data schemas

JSON Schema (draft 2020-12) definitions for the two training data formats the
project consumes. They are the **contract between the upstream synth repo
([`ollama-gpu-host-aws`](https://github.com/ericyanpek/ollama-gpu-host-aws))
and this repo's LLaMA-Factory pipeline**.

| File | For | LLaMA-Factory formatting |
|---|---|---|
| [`sft_alpaca.schema.json`](./sft_alpaca.schema.json) | Supervised fine-tuning records | `alpaca` |
| [`dpo_alpaca.schema.json`](./dpo_alpaca.schema.json) | Pairwise preference records (DPO) | `alpaca` + `ranking: true` |

## Why schemas

- **Upstream enforcement**: the synth scripts in `ollama-gpu-host-aws` validate
  against these before writing to S3. Bad samples never enter the dataset
- **Self-documenting**: every field carries a `description`. Reviewers see
  both the shape and the intent without hunting through code
- **KTO path preservation** (DPO only): the `chosen_label` / `rejected_label`
  fields are provenance markers so the same file can be re-read as single-
  label KTO data without regenerating (see [ADR-0006](../docs/adr/0006-alignment-method-sft-dpo-with-kto-optional.md))
- **Eval slicing**: optional `persona_id`, `language`, and `drift_probe`
  fields let the eval harness bucket results by probe type without needing
  a separate metadata join

## How to validate

### Python (ad hoc)

```bash
uv pip install jsonschema        # if not already in your venv
python - <<'PY'
import json
from jsonschema import Draft202012Validator
schema = json.load(open("schemas/sft_alpaca.schema.json"))
data   = json.load(open("data/sft/emotion_sft_tiny.json"))
errors = list(Draft202012Validator(schema).iter_errors(data))
if errors:
    for e in errors: print(f"{list(e.absolute_path)}: {e.message}")
    raise SystemExit(1)
print("OK")
PY
```

### Bundled into CI (planned)

A future `make validate-data` target will run both schemas against every
file in `data/sft/` and `data/dpo/` during CI. Not wired yet — this batch
focuses on getting the first samples on disk; validator integration lands
with the data pipeline scripts.

## Relation to LLaMA-Factory's own format expectations

LLaMA-Factory itself validates very loosely (it reads whatever columns you
map in `dataset_info.json` and trusts they have sensible string content).
These schemas are **our** discipline on top — catching issues like:

- empty `output` strings that would train the model on blank replies
- missing `system` fields (violates our "persona in weights" principle)
- malformed `history` pairs (must be exactly `[user, assistant]`)
- `chosen == rejected` pairs (DPO gradient would be zero; wasted sample)

## When you change a schema

1. Bump the `$id` version if the change is breaking
2. Add an ADR if the contract shape is changing (not just adding optional fields)
3. Re-validate all existing `data/**.json` files; fix or regenerate incompatible ones
4. Update the synth side in `ollama-gpu-host-aws` **before** merging
   (otherwise synth output will start failing validation)
