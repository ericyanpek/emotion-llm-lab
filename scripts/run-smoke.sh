#!/bin/bash
# run-smoke.sh — invoke the Qwen3-8B smoke training run on the EC2 instance.
# Expected to be at /home/ubuntu/run-smoke.sh; triggered via tmux by the
# Mac-side control script.
#
# Reads the HF token fresh from SSM Parameter Store at runtime so the value
# is never persisted on disk.

set -euo pipefail

# shellcheck disable=SC1091  # sourced at runtime on the training instance
source /home/ubuntu/venv-train/bin/activate
cd /home/ubuntu/LLaMA-Factory

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
  /home/ubuntu/emotion-llm-lab/configs/sft_qwen3_8b_smoke.yaml 2>&1
