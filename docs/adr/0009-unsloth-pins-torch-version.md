# ADR-0009: Unsloth dictates the torch version

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author

## Context

During the initial bootstrap we observed that `uv pip install unsloth` caused
a silent **downgrade** of several packages that earlier install steps had
pinned:

```
- torch==2.11.0+cu128         ← we installed this first
+ torch==2.10.0+cu128         ← unsloth pulled this in
- torchvision==0.26.0+cu128
+ torchvision==0.25.0+cu128
- nvidia-cudnn-cu12==9.19.0.56
+ nvidia-cudnn-cu12==9.10.2.21
- nvidia-nccl-cu12==2.28.9
+ nvidia-nccl-cu12==2.27.5
```

Unsloth ships pre-compiled CUDA kernels that require an **exact** torch
match. Its installer will aggressively downgrade the surrounding stack to
fit — and do so silently (uv reports it as a normal resolve).

Meanwhile, LLaMA-Factory v0.9.4's cpp-extension runtime check warns:

```
Skipping import of cpp extensions due to incompatible torch version.
Please upgrade to torch >= 2.11.0 (found 2.10.0+cu128).
```

So we have a hard conflict:

- **Unsloth** requires torch exactly 2.10.0
- **LLaMA-Factory cpp extensions** require torch ≥ 2.11.0

## Decision

Pin **torch to `2.10.0+cu128`** in the bootstrap SSM Document (and matching
`torchvision==0.25.0+cu128`, `torchaudio==2.10.0+cu128`), and accept the
LLaMA-Factory cpp-extension warning.

## Consequences

Good:

- **Unsloth acceleration preserved**: 2x SFT throughput + ~70% VRAM reduction
  on Qwen3-8B, which is the reason we chose Unsloth in [ADR-0002](./0002-fine-tune-framework-llama-factory.md)
- **Deterministic resolve**: with torch exact-pinned, uv cannot downgrade it
  later when installing other packages; we avoid the oscillation we saw
  during bootstrap debugging
- **No silent drift across bootstraps**: a new `make bootstrap` on a clean
  venv produces the same versions

Bad / watch-outs:

- We **lose LLaMA-Factory's native cpp extension** (custom attention kernels
  + some fused ops). Expected perf impact: low single-digit %; nothing like
  the 2x that Unsloth delivers
- We are **locked to whatever torch Unsloth pins today** (2.10.0). When
  Unsloth releases a new version compatible with torch 2.11+, we must bump
  both together, not incrementally
- **Unsloth also drags up other packages past LLaMA-Factory's declared
  upper bounds** (`datasets<=4.0.0`, `peft<=0.17.1`, etc.). The bootstrap
  SSM Document re-pins these *after* the unsloth install, restoring
  LLaMA-Factory's runtime `check_dependencies()` window. That re-pin list
  must stay synced with LLaMA-Factory's `src/llamafactory/extras/misc.py`
  on every `llama_factory_ref` bump
- **Check this ADR on every `llama_factory_ref` bump**: if a future
  LLaMA-Factory release hard-requires torch ≥ 2.11 (currently it's only a
  soft runtime warning), Unsloth becomes unusable until it catches up, and
  we must revisit this decision

## Alternatives considered

| Option | Why rejected |
|---|---|
| Drop Unsloth; use torch 2.11 with LLaMA-Factory cpp ext | Largest PoC regression — Unsloth is the single biggest perf win in our stack. The cpp-ext gains are much smaller |
| Fork Unsloth and rebuild against torch 2.11 | Multi-day detour; we want to train, not maintain a kernel repo |
| Use pip `--no-deps` to prevent Unsloth from downgrading torch | Causes broken imports — Unsloth's kernels really do need 2.10 |
| Wait for Unsloth to release a 2.11-compatible build | Unknown timeline; PoC now |

## References

- Unsloth release notes: https://www.unsloth.ai/blog
- ADR-0002 (fine-tune framework choice): [0002-fine-tune-framework-llama-factory.md](./0002-fine-tune-framework-llama-factory.md)
- ADR-0008 (train venv self-contained): [0008-train-venv-self-contained-torch.md](./0008-train-venv-self-contained-torch.md)
