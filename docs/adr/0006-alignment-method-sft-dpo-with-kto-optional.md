# ADR-0006: Alignment method: SFT + DPO (KTO path preserved)

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author

## Context

For an emotionally expressive companion model, we need two distinct
capabilities:

1. **Persona injection**: the model must consistently speak as one character
   across turns, languages, and hostile prompts
2. **Emotional alignment**: specific replies must be preferred over generic
   "as an AI I don't have feelings" templates

2026 preference alignment is a menu: DPO, KTO, IPO, GRPO, MPO, ORPO. Picking
one for a PoC matters less than picking a path that lets us switch later
with minimal data rework.

## Decision

Two-stage alignment:

1. **Stage 1 — SFT**: persona injection. Every record includes an explicit
   `system` field carrying the persona, so the behavior is baked into weights
   rather than only cued at inference
2. **Stage 2 — DPO**: emotional alignment against pairwise chosen/rejected
   preference data. `beta=0.1`, `learning_rate=5e-7..5e-6`, `ref_model: null`
   to cut VRAM on A10G

**Data-collection contract**: every preference example is logged as both
chosen/rejected (DPO-ready) and with a binary label (KTO-ready), so we can
switch algorithms without rebuilding the dataset.

## Consequences

Good:

- DPO is the 2026 standard for style/tone/safety alignment; richest community
  support in LLaMA-Factory, TRL, and eval literature
- Logging both formats costs almost nothing in data pipeline, but buys us
  the ability to try KTO (single-label, cheaper to collect from user
  thumbs-up / thumbs-down signals) without rebuilding the dataset
- Reference-free DPO mode keeps peak VRAM inside the A10G 24GB envelope

Bad / watch-outs:

- DPO with small beta can over-align; always report reward margin distribution
  in addition to loss
- Pairwise preference data is labor-intensive. Once the App is live, pivoting
  to KTO (from user-provided single labels) is likely the scalable path —
  budget for that pivot from day one
- DPO does **not** teach new facts or capabilities. If the emotional deficit
  comes from missing training data (e.g. a new language), DPO just sharpens
  existing patterns; revisit SFT data first before blaming DPO

## Alternatives considered

| Option | Why rejected |
|---|---|
| RLHF (PPO) | Online RL with a reward model is expensive and unstable at 8B on A10G; we gain no meaningful capability over DPO for style alignment |
| KTO as primary | Simpler data collection once App is live, but community tooling and eval benchmarks still lag DPO; keep as Stage-2 option |
| ORPO (single-stage SFT+pref) | Promising but relatively new; prefer two distinct stages so failures are diagnosable (is it persona or alignment?) |
| GRPO | Shines on reasoning chains, overkill for companion-style alignment |
| Prompt engineering only (no DPO) | System prompts drift in long conversations; persona must be in weights for robustness |

## References

- Spheron DPO 2026 guide: https://www.spheron.network/blog/dpo-fine-tuning-gpu-cloud/
- KTO paper: "Kahneman-Tversky vs. Direct Preference Optimization", arXiv 2502.14187
- TRL multi-method alignment: https://huggingface.co/blog/trl-vlm-alignment
