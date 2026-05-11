# LLaMA-Factory training configs

YAML files that drive `llamafactory-cli train`. One file per experiment; the
evolution from smoke test → v1 → future iterations is captured by naming,
not by editing a single file (which would lose history).

## File naming

```
<stage>_<model>_<dataset-or-iteration>.yaml
```

| File | Purpose |
|---|---|
| [`sft_qwen3_8b_smoke.yaml`](./sft_qwen3_8b_smoke.yaml) | 10-step smoke test on the committed tiny dataset. Verifies the training loop runs end-to-end — downloads model, tokenizes data, LoRA trains, saves adapter. Not meant to produce a useful model |
| [`sft_qwen3_8b_v1.yaml`](./sft_qwen3_8b_v1.yaml) | First real SFT run on `emotion_sft_en_v1` (data to be produced by the synth repo). `### diff-from-smoke` comments highlight every parameter that intentionally differs from the smoke config |
| [`dpo_qwen3_8b_smoke.yaml`](./dpo_qwen3_8b_smoke.yaml) | 10-step DPO smoke test. Consumes the SFT smoke adapter as starting point and applies preference optimization on the 5 pair tiny dataset. Verifies the DPO loop (chosen/rejected, reference-free mode) works end-to-end |
| [`dpo_qwen3_8b_v1.yaml`](./dpo_qwen3_8b_v1.yaml) | First real DPO run on top of SFT v1 adapter, using `emotion_dpo_en_v1` preference data |

Future additions:
- `sft_qwen3_8b_v1_multi.yaml` — multilingual SFT with `mix_strategy: interleave_under`

## How to run

On the training instance:

```bash
source ~/venv-train/bin/activate
cd ~/LLaMA-Factory

# SFT: the first run (chain of: smoke → v1 → v1_multi)
bash /home/ubuntu/emotion-llm-lab/scripts/run-smoke.sh

# DPO: after SFT smoke has produced an adapter, run in sequence:
bash /home/ubuntu/emotion-llm-lab/scripts/run-dpo-smoke.sh

# Direct invocation (without the wrappers), if you want to customize env vars:
llamafactory-cli train /home/ubuntu/emotion-llm-lab/configs/sft_qwen3_8b_smoke.yaml
llamafactory-cli train /home/ubuntu/emotion-llm-lab/configs/dpo_qwen3_8b_smoke.yaml
```

Progress streams to stdout; TensorBoard logs land in
`saves/<...>/logs/` and are reachable at `http://localhost:6006` once
`make tunnel` is running on your Mac.

## Smoke-test success criteria

### SFT (`sft_qwen3_8b_smoke.yaml`)

- Model downloads from HF (~16 GB, takes 5-10 min first time)
- Tokenization completes (5 records, trivial)
- 10 training steps complete without OOM
- Loss at step 10 < loss at step 1 (any downward trend is fine)
- An adapter lands in `saves/sft/qwen3-8b-tiny-smoke/adapter_model.safetensors`
- No CUDA errors in logs

### DPO (`dpo_qwen3_8b_smoke.yaml`)

Run this **after** SFT smoke succeeds — DPO's `adapter_name_or_path` points
at the SFT smoke output:

- SFT adapter loads cleanly (look for `Merged X adapter(s)` in log, not
  re-downloading the base model)
- 10 DPO steps complete without OOM
- `rewards/accuracies` metric > 0.5 on at least some steps (model learns to
  prefer `chosen` over `rejected` — with 5 pairs this will be noisy but
  should not be flat at 0)
- `rewards/margins` trends positive (chosen_reward - rejected_reward > 0)
- A DPO adapter lands in `saves/dpo/qwen3-8b-emotion-tiny-smoke/adapter_model.safetensors`

If all bullets hold, DPO v1 is trustworthy to wire up.

## Debugging smoke-test failures

### Common to SFT and DPO

| Symptom | Likely cause | Fix |
|---|---|---|
| `torch.cuda.OutOfMemoryError` | LoRA rank/batch/cutoff too high | keep `lora_rank: 16`, `per_device_train_batch_size: 1`, `gradient_checkpointing: true`; DPO additionally needs `cutoff_len: 1024` |
| `Cannot find dataset_info.json` | Wrong `dataset_dir` | use absolute path: `dataset_dir: /home/ubuntu/emotion-llm-lab/data` |
| `401` on Qwen3 download | HF token missing / no access | `aws ssm get-parameter --name /emotion-companion/dev/hf-token --with-decryption`, set `HF_TOKEN` env var |
| `datasets X.Y.Z is required but found ...` | LLaMA-Factory runtime check rejected a package | see runbook: [docs/runbooks/first-deploy.md](../docs/runbooks/first-deploy.md#three-more-pitfalls-youll-hit-after-bootstrap-succeeds) |
| Loss/margin flat at 0 | LoRA adapter didn't attach to any module | confirm `lora_target: all` and the template is `qwen`, not `default` |
| Training finishes but adapter is empty | save callback didn't trigger | check `save_steps` ≤ `max_steps` |
| `Some keys are not used by the HfArgumentParser` | Field is typed wrong for `parse_dict`, or you passed both YAML + CLI flags | don't mix YAML + CLI flags; don't set `compute_dtype` as a string |

### DPO-specific

| Symptom | Likely cause | Fix |
|---|---|---|
| `adapter_name_or_path not found` | SFT smoke didn't produce an adapter at the expected path | rerun SFT smoke; check `saves/sft/qwen3-8b-tiny-smoke/adapter_model.safetensors` exists |
| `ValueError: must provide chosen and rejected` | `ranking: true` missing on dataset | confirm `dataset_info.json` entry for `emotion_dpo_tiny` has `"ranking": true` |
| `rewards/accuracies == 0` every step | Preference signal is indistinguishable (e.g. `chosen == rejected` somewhere) or LR too low | validate data with `schemas/dpo_alpaca.schema.json`; check preference data diversity; bump `learning_rate` up by 2-3x |
| `rewards/margins` negative at the end | Model prefers `rejected` (sign flipped) | verify `chosen` and `rejected` aren't swapped in the JSON; check `pref_loss: sigmoid` |
| Out of memory on DPO (not SFT) | `ref_model` accidentally pointing at a separate model, doubling VRAM | set `ref_model: null` so the base+frozen-adapter acts as reference |

## Hyperparameter reference

See [ADR-0001](../docs/adr/0001-base-model-qwen3-8b.md),
[ADR-0002](../docs/adr/0002-fine-tune-framework-llama-factory.md), and
[ADR-0006](../docs/adr/0006-alignment-method-sft-dpo-with-kto-optional.md)
for the rationale behind major choices (LoRA rank, QLoRA bit-width, DPO
beta, etc.). Don't invent alternatives without updating the corresponding
ADR — consistency across experiments is how comparisons stay meaningful.
