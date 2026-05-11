#!/bin/bash
# run-dpo-smoke.sh — DPO smoke test on the training instance.
#
# Mirrors run-smoke.sh (SFT) but points at the DPO config. Requires that
# the SFT smoke has already run (DPO consumes its adapter).
#
# Fetches the HF token from SSM Parameter Store at runtime so it's never
# written to disk.

set -euo pipefail

# shellcheck disable=SC1091  # sourced at runtime on the training instance
source /home/ubuntu/venv-train/bin/activate
cd /home/ubuntu/LLaMA-Factory

# Pre-flight: SFT adapter must exist (DPO adapter_name_or_path points at it).
SFT_ADAPTER=/home/ubuntu/emotion-llm-lab/saves/sft/qwen3-8b-tiny-smoke
if [ ! -f "${SFT_ADAPTER}/adapter_model.safetensors" ]; then
  echo "ERROR: SFT smoke adapter not found at ${SFT_ADAPTER}" >&2
  echo "Run the SFT smoke first: bash /home/ubuntu/emotion-llm-lab/scripts/run-smoke.sh" >&2
  exit 1
fi

HF_TOKEN=$(aws ssm get-parameter \
  --name /emotion-companion/dev/hf-token \
  --with-decryption \
  --query Parameter.Value \
  --output text \
  --region us-east-1)
export HF_TOKEN
export HF_HOME=/home/ubuntu/.cache/huggingface
export AWS_DEFAULT_REGION=us-east-1

mkdir -p /home/ubuntu/emotion-llm-lab/saves

exec llamafactory-cli train \
  /home/ubuntu/emotion-llm-lab/configs/dpo_qwen3_8b_smoke.yaml 2>&1
