# Emotion Companion LLM Fine-Tune Research

PoC for fine-tuning an open-weight LLM (Qwen3-8B) into an emotionally expressive,
globally multilingual companion model. Pipeline: SFT (persona injection) → DPO
(emotional alignment) → vLLM serving.

## Stack

| Layer | Choice |
|---|---|
| Base model | Qwen3-8B (Apache 2.0, 119 languages) |
| Fine-tune framework | LLaMA-Factory + Unsloth (QLoRA 4-bit) |
| Training hardware | EC2 `g5.2xlarge` (NVIDIA A10G 24GB) |
| Local dev | MacBook Pro M-series 48GB (MLX for local eval) |
| Serving | vLLM with multi-LoRA support |
| Remote access | AWS SSM Session Manager (zero public ports) |
| Artifact storage | S3 (data + LoRA adapters) |
| Python / deps | Python 3.11 + `uv` + PEP 735 dependency groups |

## Python environments

Three environments, all pinned to **Python 3.11** (matches the DLAMI):

| Environment | Host | Deps group | Purpose |
|---|---|---|---|
| `.venv` | Mac | `local`+`eval`+`dev` | data prep, eval harness, MLX local inference |
| `~/venv-train` | EC2 | `train` (+ DLAMI torch) | LLaMA-Factory QLoRA training |
| `~/venv-serve` | EC2 | `serve` | vLLM inference (separate venv — conflicts with train) |

Mac setup:

```bash
uv sync --group local --group eval --group dev
source .venv/bin/activate
```

The EC2 venvs are built automatically by the CloudFormation user-data.

## Repository layout

```
.
├── pyproject.toml           # Python 3.11 + deps groups: local / eval / train / serve / dev
├── .python-version          # 3.11 (uv auto-detects)
├── uv.lock                  # pinned dependency versions (commit this)
├── infrastructure/          # CloudFormation + ops scripts
│   ├── cloudformation/
│   │   └── training-env.yaml
│   └── scripts/
│       ├── deploy.sh        # create / update stack
│       ├── destroy.sh       # tear down stack
│       ├── tunnel.sh        # SSM port-forward (webui + tensorboard + vllm)
│       └── ssm-shell.sh     # interactive shell via SSM
├── configs/                 # LLaMA-Factory training configs (SFT, DPO)
├── data/                    # local data workspace (gitignored, use S3)
├── scripts/                 # data prep, eval, conversion scripts
└── docs/                    # design notes
```

## Getting started

1. [Deploy training infrastructure](./infrastructure/README.md)
2. Connect via SSM tunnel
3. Install LLaMA-Factory on EC2
4. Prep data → SFT → DPO → eval (coming next)

## Status

- [x] Infrastructure: CloudFormation stack + SSM tunnel scripts
- [ ] Data pipeline: schema + dataset_info.json
- [ ] SFT training config
- [ ] DPO training config
- [ ] Eval harness (LLM-as-judge + persona drift probes)
- [ ] vLLM serving

## License

MIT-0 for code. Model weights and data subject to their respective licenses.
