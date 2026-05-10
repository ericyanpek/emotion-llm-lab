#!/usr/bin/env bash
# tunnel.sh — SSM Port Forwarding from MacBook → training instance.
#
# Forwards three ports via AWS SSM (zero public ports needed on EC2):
#   - 7860: LLaMA-Factory Gradio webui
#   - 6006: TensorBoard
#   - 8000: vLLM inference server (used after training)
#
# Note: AWS-StartPortForwardingSession accepts exactly ONE port per session, so
# we spawn one subprocess per port and trap SIGINT/SIGTERM to clean them all
# up together. Each subprocess logs to /tmp/ssm-tunnel-<port>.log for debugging.
#
# Requires: AWS CLI v2 + Session Manager Plugin
#   brew install --cask session-manager-plugin
#
# Usage:
#   ./infrastructure/scripts/tunnel.sh
#   PORTS=7860 ./infrastructure/scripts/tunnel.sh          # webui only
#   STACK_NAME=... AWS_REGION=... ./infrastructure/scripts/tunnel.sh

set -euo pipefail

STACK_NAME="${STACK_NAME:-emotion-companion-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
# Default: 7860 (webui) 6006 (tensorboard) 8000 (vllm OpenAI API). Override with PORTS="7860".
PORTS="${PORTS:-7860 6006 8000}"

# Check session-manager-plugin is installed.
if ! command -v session-manager-plugin >/dev/null 2>&1; then
  echo "ERROR: session-manager-plugin is not installed." >&2
  echo "Install it with: brew install --cask session-manager-plugin" >&2
  exit 1
fi

# Look up the instance ID from CloudFormation outputs.
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

echo "Starting SSM port forwarding tunnels..."
echo "  Instance: $INSTANCE_ID"
echo "  Region:   $AWS_REGION"
echo "  Ports:    $PORTS"
echo

# Track child PIDs so we can clean them up on exit.
PIDS=()
cleanup() {
  echo
  echo "Stopping tunnels..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  # Give them a moment, then force kill anything still alive.
  sleep 1
  for pid in "${PIDS[@]}"; do
    kill -9 "$pid" 2>/dev/null || true
  done
  exit 0
}
trap cleanup INT TERM

# Start one SSM port-forwarding session per port.
for port in $PORTS; do
  log="/tmp/ssm-tunnel-${port}.log"
  : > "$log"  # truncate

  aws ssm start-session \
    --target "$INSTANCE_ID" \
    --region "$AWS_REGION" \
    --document-name AWS-StartPortForwardingSession \
    --parameters "{\"portNumber\":[\"${port}\"],\"localPortNumber\":[\"${port}\"]}" \
    >> "$log" 2>&1 &
  pid=$!
  PIDS+=("$pid")
  echo "  port ${port}: pid ${pid}  (log: ${log})"
done

echo
echo "Once all tunnels are 'Waiting for connections' in their logs, open in your browser:"
echo "  LLaMA-Factory webui: http://localhost:7860"
echo "  TensorBoard:         http://localhost:6006"
echo "  vLLM OpenAI API:     http://localhost:8000"
echo
echo "Ctrl+C to stop all tunnels (training keeps running on the instance)."
echo

# Poll: if any child dies unexpectedly, surface it. Otherwise wait.
while true; do
  for pid in "${PIDS[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "WARNING: tunnel pid $pid exited. See /tmp/ssm-tunnel-*.log for detail." >&2
      cleanup
    fi
  done
  sleep 3
done
