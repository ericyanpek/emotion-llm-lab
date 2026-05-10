#!/usr/bin/env bash
# ssm-shell.sh — Interactive shell on the training instance via SSM.
#
# Lands in ssm-user by default. Switch to ubuntu for the conda/python env:
#   sudo su - ubuntu
#
# Resume or start your tmux training session:
#   tmux attach -t train || tmux new -s train
#
# Usage:
#   ./infrastructure/scripts/ssm-shell.sh

set -euo pipefail

STACK_NAME="${STACK_NAME:-emotion-companion-dev}"
AWS_REGION="${AWS_REGION:-us-west-2}"

# shellcheck disable=SC2016  # JMESPath literal below; intentionally not shell-expanded
INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' \
  --output text)

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
  echo "ERROR: could not find InstanceId output on stack $STACK_NAME." >&2
  exit 1
fi

echo "Starting SSM shell on $INSTANCE_ID ($AWS_REGION)..."
echo "Tip: run 'sudo su - ubuntu' to switch to the ubuntu user."
echo

exec aws ssm start-session --target "$INSTANCE_ID" --region "$AWS_REGION"
