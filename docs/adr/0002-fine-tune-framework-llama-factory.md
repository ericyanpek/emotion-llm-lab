# ADR-0002: Fine-tune framework: LLaMA-Factory + Unsloth

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author

## Context

Given the chosen base model (Qwen3-8B, see [ADR-0001](./0001-base-model-qwen3-8b.md))
and hardware (A10G 24GB, see [ADR-0003](./0003-training-hardware-ec2-g5-dlami.md)),
we need a framework that supports:

- **QLoRA 4-bit** training (hard constraint for 8B on 24GB)
- Both **SFT and DPO** (our two-stage alignment plan, see [ADR-0006](./0006-alignment-method-sft-dpo-with-kto-optional.md))
- **Multi-LoRA** inference serving for multilingual adapter routing
- A web UI for fast iteration during PoC
- Strong community so bugs and new-model support arrive quickly

## Decision

Use **LLaMA-Factory** as the training orchestrator, with **Unsloth** as the
acceleration backend during SFT. DPO uses LLaMA-Factory's native TRL backend
(not Unsloth).

## Consequences

Good:

- YAML-first training configs → reproducible experiments, easy diffs in PRs
- Web UI (Gradio 7860) for PoC iteration; CLI for scripted runs
- Native `ref_model: null` DPO mode that loads base + frozen adapter as
  reference, cutting peak VRAM roughly in half
- Unsloth on Qwen3 delivers ~2x SFT speedup and ~70% less VRAM (published
  benchmarks), extending the A10G runway
- `llamafactory-cli export` handles LoRA merge for vLLM serving with one
  command

Bad / watch-outs:

- Unsloth lags on brand-new model releases; we track the LLaMA-Factory main
  branch and accept occasional incompatibility
- Unsloth **does not** accelerate DPO/KTO reliably; we fall back to the
  vanilla TRL path for alignment — plan for it
- LLaMA-Factory's CLI is the stable surface; the Python API surface is
  evolving — prefer CLI over `from llmtuner import ...`

## Alternatives considered

| Option | Why rejected |
|---|---|
| Direct `transformers` + `peft` + `trl` | Significantly more boilerplate per experiment; LLaMA-Factory is a thin wrapper over the same libraries |
| Axolotl | Comparable scope; smaller community around Qwen models; YAML schema churns more frequently than LLaMA-Factory |
| SageMaker Training Jobs | Useful for prod-scale, but cold-start 10+ min per run and poor interactive loop kill PoC velocity — defer to migration phase |
| Hugging Face AutoTrain | Hosted-only convenience; lacks the DPO + multi-LoRA control we need |

## References

- LLaMA-Factory README: https://github.com/hiyouga/LLaMA-Factory
- Unsloth Qwen3 notebook: https://www.unsloth.ai/blog/qwen3
