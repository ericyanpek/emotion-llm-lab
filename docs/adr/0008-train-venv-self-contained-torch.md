# ADR-0008: Train venv carries its own torch stack

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author
- **Supersedes (partially):** [ADR-0005](./0005-python-311-uv-dependency-groups.md)
  (the `--system-site-packages` strategy for the train venv)

## Context

ADR-0005 specified building the train venv on top of DLAMI's `/opt/pytorch`
via `uv venv --system-site-packages`, the rationale being to inherit the
pre-compiled CUDA-matched torch stack.

Real deployment revealed this is **unenforceable**:

- LLaMA-Factory's `pyproject.toml` hard-lists `torch>=2.4.0` in `dependencies`
- uv's dependency resolver treats inherited packages as starting points, but
  reinstalls into the venv when any transitive constraint disagrees
- Installing `llamafactory[...]` consistently caused uv to fetch torch from
  PyPI (CPU wheels), overwriting the DLAMI-provided CUDA build

Secondary issues uncovered during debugging:

- `--extra-index-url` only applies to the single `uv pip install` command
  that receives it; subsequent installs revert to PyPI defaults, which makes
  CUDA-vs-CPU wheel selection non-deterministic across steps
- LLaMA-Factory v0.9.4 under-specifies `build-system.requires` (missing
  `editables` that hatchling needs for editable installs), so `--no-build-
  isolation` plus a minimal venv fails until build backends are seeded
  explicitly

## Decision

The train venv is **self-contained**:

- Built with `uv venv --python /opt/pytorch/bin/python` (DLAMI's python), but
  **without** `--system-site-packages`
- CUDA wheel selection pinned via `UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu128`
  and `UV_INDEX_STRATEGY=unsafe-best-match` **exported for all `uv pip install`
  calls** in the bootstrap step
- Build backends (`hatchling`, `editables`, `setuptools`, `wheel`) seeded
  before the editable LLaMA-Factory install
- torch version pinned to `2.10.0+cu128` — see [ADR-0009](./0009-unsloth-pins-torch-version.md)
  for why exact-pin matters

## Consequences

Good:

- **Reproducible**: every bootstrap yields the same torch / CUDA / cuDNN
  versions regardless of DLAMI release cadence
- **Debuggable**: when something fails, we reason about *our* venv, not the
  intersection of our venv and DLAMI's inherited packages
- **Decoupled from DLAMI upgrades**: a new DLAMI AMI with different torch
  doesn't change our training stack

Bad / watch-outs:

- ~5 GB extra disk (we download a full torch + CUDA runtime despite DLAMI
  already having one at `/opt/pytorch`). Factored into the 500 GB gp3 sizing
- First bootstrap ~2-3 min slower (torch/CUDA wheel download)
- Non-idempotent *version* pins: if we bump `torch==2.10.0+cu128` to a newer
  release, uv will **downgrade** other packages that constrain torch; rerun
  requires a clean venv (`rm -rf ~/venv-train`) to be safe
- **`UV_EXTRA_INDEX_URL` must be exported in every SSM Document step** that
  calls `uv pip install` against torch-related packages. Missing it in even
  one step causes silent downgrade from cu128 wheels to CPU wheels

## Alternatives considered

| Option | Why rejected |
|---|---|
| Keep `--system-site-packages` + workaround torch reinstalls | No reliable workaround; uv's resolver is designed to upgrade, not respect host |
| Use DLAMI python directly without venv (pip into /opt/pytorch) | Pollutes DLAMI env, violates venv hygiene, no clean rollback |
| Switch to conda / pip with constraint files | Re-introduces tools we already ejected in ADR-0005; constraint files can't bypass the `torch>=2.4.0` dependency declaration anyway |
| Fork LLaMA-Factory and delete the torch dep | Maintenance burden; breaks on every upstream release |

## References

- uv env var reference (UV_EXTRA_INDEX_URL, UV_INDEX_STRATEGY):
  https://docs.astral.sh/uv/reference/environment/
- PyTorch CUDA 12.8 wheel index: https://download.pytorch.org/whl/cu128/
- ADR-0005 (partially superseded by this): [0005-python-311-uv-dependency-groups.md](./0005-python-311-uv-dependency-groups.md)
- ADR-0009 (why exact torch pin): [0009-unsloth-pins-torch-version.md](./0009-unsloth-pins-torch-version.md)
