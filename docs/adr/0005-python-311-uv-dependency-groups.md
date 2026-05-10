# ADR-0005: Python 3.11 pinned, uv with PEP 735 dependency groups

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author

## Context

Three separate execution environments share the same codebase:

1. **Mac local**: data cleaning, eval scripts, MLX-based local inference
2. **EC2 train venv**: LLaMA-Factory + QLoRA training, must reuse DLAMI's
   pre-built `torch` (see [ADR-0003](./0003-training-hardware-ec2-g5-dlami.md))
3. **EC2 serve venv**: vLLM, which has dependency conflicts with training
   stacks and must be isolated

Historical failure modes we want to avoid:

- Developer has Python 3.10; some ML library assumes walrus operator with
  match/case → silent breakage
- Developer reinstalls `torch` in the EC2 train venv → breaks CUDA/
  flash-attn/bitsandbytes alignment the DLAMI carefully assembled
- `pyproject.toml` uses `optional-dependencies` → all deps load whether you
  need them or not; `vllm` gets pulled into the training image

## Decision

- Pin **Python 3.11** via `.python-version` (matches DLAMI PyTorch 2.7 AMI)
- Use **uv** as the package manager and Python version manager
- Declare dependencies in `pyproject.toml` under **PEP 735 dependency groups**:
  `local`, `eval`, `train`, `serve`, `dev`
- Commit `uv.lock` for reproducibility
- The `train` group **deliberately does not list `torch`**. On EC2 the train
  venv is built with `uv venv --python /opt/pytorch/bin/python
  --system-site-packages` so DLAMI's torch is inherited, not overwritten

## Consequences

Good:

- One Python version across all three environments eliminates a class of bugs
- Groups map cleanly to contexts: Mac installs `local + eval + dev`; EC2
  train installs `train`; EC2 serve installs `serve`
- `uv sync --locked` in CI enforces that the lock file matches the manifest
- Installs are ~10x faster than pip (noticeable during CI cold starts and
  when installing vLLM)
- uv's built-in Python management (`uv python install 3.11`) removes the
  need for pyenv on top

Bad / watch-outs:

- PEP 735 groups are new enough that some tools don't recognize them — we
  depend on uv specifically. Migrating to pip/poetry would require touching
  the manifest
- `--system-site-packages` leaks every DLAMI-installed package into the
  train venv. This is deliberate (we *want* DLAMI's torch) but means
  `uv pip install` could be tempted to upgrade them. Reviewers watch for
  torch/flash-attn/bitsandbytes in diff output
- `uv.lock` is large (~500KB) and changes noisily on dependency bumps;
  reviewers skim it, don't audit every line

## Alternatives considered

| Option | Why rejected |
|---|---|
| pip + requirements.txt | No group concept; no lockfile; torch vs training deps mix freely |
| Poetry | Slower, has its own lockfile dialect, doesn't manage Python versions — pyenv required |
| conda / mamba | Heavier; mixing conda-forge and pip in the same env remains a known hazard; DLAMI already is a conda-flavoured world and we inherit that |
| pyenv + pip-tools | Two tools where uv is one; no deduplication of Python version pin |

## References

- PEP 735 (Dependency Groups): https://peps.python.org/pep-0735/
- uv docs: https://docs.astral.sh/uv/
- `pyproject.toml` in this repo documents the group design inline
