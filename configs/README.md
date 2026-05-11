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

Future additions:
- `dpo_qwen3_8b_v1.yaml` — DPO stage on top of SFT v1 adapter
- `sft_qwen3_8b_v1_multi.yaml` — multilingual SFT with `mix_strategy: interleave_under`

## How to run

On the training instance:

```bash
source ~/venv-train/bin/activate
cd ~/LLaMA-Factory

# Copy the config from the project repo (which lives elsewhere) or mount it.
# Option A: clone this repo on the instance and point to the configs dir
# Option B: edit via webui (`make tunnel` then http://localhost:7860) and
#          "Load" the YAML through the UI

llamafactory-cli train /home/ubuntu/emotion-llm-lab/configs/sft_qwen3_8b_smoke.yaml
```

Progress streams to stdout; TensorBoard logs land in
`saves/<...>/logs/` and are reachable at `http://localhost:6006` once
`make tunnel` is running on your Mac.

## Smoke-test success criteria

- Model downloads from HF (~16 GB, takes 5-10 min first time)
- Tokenization completes (5 records, trivial)
- 10 training steps complete without OOM
- Loss at step 10 < loss at step 1 (any downward trend is fine)
- An adapter lands in `saves/sft/qwen3-8b-tiny-smoke/adapter_model.safetensors`
- No CUDA errors in logs

If all six hold, the v1 config can be run with confidence.

## Debugging smoke-test failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `torch.cuda.OutOfMemoryError` | LoRA rank/batch too high for available VRAM | keep `lora_rank: 16`, `per_device_train_batch_size: 1`, `gradient_checkpointing: true` |
| `Cannot find dataset_info.json` | Wrong `dataset_dir` or running from the wrong cwd | set absolute path: `dataset_dir: /home/ubuntu/emotion-llm-lab/data` |
| `401` on Qwen3 download | HF token missing / no access | `aws ssm get-parameter --name /emotion-companion/dev/hf-token --with-decryption`, set `HF_TOKEN` env var |
| `datasets X.Y.Z is required but found ...` | LLaMA-Factory version check rejected a package | see runbook: [docs/runbooks/first-deploy.md](../docs/runbooks/first-deploy.md#three-more-pitfalls-youll-hit-after-bootstrap-succeeds) |
| Loss flat at 0 | LoRA adapter didn't attach to any module | confirm `lora_target: all` and the template is `qwen`, not `default` |
| Training finishes but adapter is empty | save callback didn't trigger | check `save_steps` ≤ `max_steps` |

## Hyperparameter reference

See [ADR-0001](../docs/adr/0001-base-model-qwen3-8b.md),
[ADR-0002](../docs/adr/0002-fine-tune-framework-llama-factory.md), and
[ADR-0006](../docs/adr/0006-alignment-method-sft-dpo-with-kto-optional.md)
for the rationale behind major choices (LoRA rank, QLoRA bit-width, DPO
beta, etc.). Don't invent alternatives without updating the corresponding
ADR — consistency across experiments is how comparisons stay meaningful.
