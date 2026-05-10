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

## Repository layout

```
.
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
