#!/usr/bin/env bash
# tunnel.sh — SSM Port Forwarding from MacBook → training instance.
#
# Forwards three ports via AWS SSM (zero public ports needed on EC2):
#   - 7860: LLaMA-Factory Gradio webui
#   - 6006: TensorBoard
#   - 8000: vLLM inference server (used after training)
#
# Requires: AWS CLI v2 + Session Manager Plugin
#   brew install --cask session-manager-plugin
#
# Usage:
#   ./infrastructure/scripts/tunnel.sh
#   STACK_NAME=... AWS_REGION=... ./infrastructure/scripts/tunnel.sh

set -euo pipefail

STACK_NAME="${STACK_NAME:-emotion-companion-dev}"
AWS_REGION="${AWS_REGION:-us-west-2}"

# Check session-manager-plugin is installed.
if ! command -v session-manager-plugin >/dev/null 2>&1; then
  echo "ERROR: session-manager-plugin is not installed." >&2
  echo "Install it with: brew install --cask session-manager-plugin" >&2
  exit 1
fi

# Look up the instance ID from CloudFormation outputs.
INSTANCE_ID=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' \
  --output text)

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
  echo "ERROR: could not find InstanceId output on stack $STACK_NAME." >&2
  exit 1
fi

echo "Starting SSM port forwarding tunnel..."
echo "  Instance: $INSTANCE_ID"
echo "  Region:   $AWS_REGION"
echo
echo "Once connected, open in your browser:"
echo "  LLaMA-Factory webui: http://localhost:7860"
echo "  TensorBoard:         http://localhost:6006"
echo "  vLLM OpenAI API:     http://localhost:8000"
echo
echo "Ctrl+C to stop the tunnel (training keeps running on the instance)."
echo

aws ssm start-session \
  --target "$INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["7860","6006","8000"],"localPortNumber":["7860","6006","8000"]}'
