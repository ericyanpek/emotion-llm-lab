# ADR-0003: Training hardware: EC2 g5.2xlarge + DLAMI

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author

## Context

Qwen3-8B QLoRA training on a single GPU needs ~16-20GB VRAM (SFT) and up to
~22GB (DPO with reference-free mode). Longer contexts or larger LoRA ranks
push higher. We also need CUDA + flash-attn + bitsandbytes versions that are
known-compatible — building that stack from scratch is a multi-hour yak shave.

## Decision

Use **EC2 g5.2xlarge** (1x NVIDIA A10G 24GB, 8 vCPU, 32GB RAM) as the default
training instance, booted from the **AWS Deep Learning OSS AMI Nvidia Driver
GPU PyTorch 2.7 (Ubuntu 22.04)** resolved via the public SSM parameter
`/aws/service/deeplearning/ami/x86_64/oss-nvidia-driver-gpu-pytorch-2.7-ubuntu-22.04/latest/ami-id`.

Instance type is a CloudFormation parameter so upsizing to g5.4xlarge,
g6.2xlarge (L4), or g6e.2xlarge (L40S 48GB) is a one-line change.

## Consequences

Good:

- 24GB VRAM fits Qwen3-8B QLoRA SFT and DPO with room for DeepSpeed ZeRO-2
- DLAMI ships a CUDA-matched PyTorch 2.7, flash-attn, bitsandbytes, NCCL
  stack — we skip hours of "why doesn't `pip install torch` work"
- SSM parameter resolution means we always boot on the latest patched AMI
  without pinning a stale `ami-xxxxx` in the template
- A10G On-Demand ~$1.2/hr in us-east-1; 8-hour training day ~$10 keeps PoC
  cheap if we remember to stop the instance

Bad / watch-outs:

- A10G is older than L4/L40S; long-context (>4K) training is slower than
  newer GPUs. We mitigate with `cutoff_len: 2048` for SFT, 1024 for DPO
- Because DLAMI owns `/opt/pytorch`, our train venv uses
  `--system-site-packages` to inherit it — **reinstalling torch in the
  train venv will break CUDA alignment** (see [ADR-0005](./0005-python-311-uv-dependency-groups.md))
- Spot g5 interruption rates are higher than x86 CPU families. PoC default
  is On-Demand; flip `UseSpotInstance: true` when LLaMA-Factory
  checkpoint-resume is proven

## Alternatives considered

| Option | Why rejected |
|---|---|
| g5.xlarge (16GB RAM) | DPO reference model + optimizer state risks OOM on RAM side; the $0.2/hr saving isn't worth a failed training run |
| g6.2xlarge (L4 24GB) | Equally viable; L4 newer but g5 has deeper community recipes in LLaMA-Factory for Qwen. Listed in AllowedValues as alternative |
| g6e.2xlarge (L40S 48GB) | Overkill for 8B QLoRA; reserve for 14B upgrade path |
| Ubuntu base AMI + manual driver | 2-4h install, fragile version matrix, no benefit |
| EC2 Mac instances | 24h minimum allocation, wrong architecture for CUDA workloads |

## References

- DLAMI SSM parameter docs: https://docs.aws.amazon.com/dlami/latest/devguide/aws-deep-learning-x86-gpu-pytorch-2.7-ubuntu-22-04.html
- g5 pricing: AWS EC2 pricing page (us-east-1, on-demand $1.212/hr at decision date)
