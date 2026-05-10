# ADR-0001: Base model: Qwen3-8B

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author

## Context

We need an open-weight base model to fine-tune into an emotionally expressive,
globally multilingual companion. Constraints:

- **License** must permit global commercial distribution without MAU caps
- **Languages**: the target App is globally released, so broad multilingual
  coverage matters more than maximal English quality
- **Hardware budget**: fine-tuning and inference should fit on a single
  NVIDIA A10G 24GB (EC2 g5.2xlarge) to keep PoC costs manageable
- **Ecosystem**: must be first-class supported by LLaMA-Factory, Unsloth,
  vLLM on the release date of this ADR

## Decision

Use **Qwen3-8B-Instruct** (Alibaba, released April 2025) as the base model.

## Consequences

Good:

- Apache 2.0 — clean for global commercial use, no MAU ceiling
- 119 languages natively covered (vs Qwen2.5's 29, Llama 4's officially 12)
- Fits comfortably on A10G 24GB with QLoRA 4-bit (~6-8GB weights, headroom
  for DPO reference model)
- First-class support in LLaMA-Factory and Unsloth (2x training speedup
  verified on Qwen3 family)
- Strong Chinese and East Asian language performance preserved (important
  for APAC markets) without sacrificing European language quality

Bad / watch-outs:

- Qwen3 Thinking mode on by default in some checkpoints — must explicitly
  use the non-thinking Instruct variant for companion-style output
- Some eval benchmarks favor English; need our own multilingual eval harness
- Alibaba-origin model may require additional due-diligence in some regulated
  deployment regions

## Alternatives considered

| Option | Why rejected |
|---|---|
| Llama 4 Scout (17B active / 109B MoE) | Doesn't fit A10G single-GPU; Llama license has 700M MAU cap that risks rework if App scales |
| Qwen3-30B-A3B (MoE) | More flexible for multilingual but MoE LoRA ecosystem still maturing; deferred to "upgrade path" |
| Gemma 4 (31B Dense) | Apache 2.0 as of 2026-04, 140 languages — strong option but 31B dense doesn't fit A10G; LLaMA-Factory adapter maturity lagged at decision time |
| Mistral Small 3.1 (24B) | Strong multilingual but 24B dense exceeds A10G for full-precision DPO reference |
| Qwen2.5-7B | Previous default; only 29 languages makes global App story weak |

## References

- Initial review → web search results on 2026-05-10 showed Qwen3 as the
  2026 open-source multilingual first pick (siliconflow.com multilingual
  ranking, qwen-ai.com roadmap)
- Unsloth Qwen3 support blog: https://www.unsloth.ai/blog/qwen3
