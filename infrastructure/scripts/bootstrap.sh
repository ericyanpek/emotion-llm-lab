#!/usr/bin/env bash
# bootstrap.sh — Install the training stack on the EC2 instance via SSM.
#
# This runs the SSM Document defined in training-env.yaml on the instance,
# installing uv, LLaMA-Factory, Unsloth, and vLLM in two separate venvs.
#
# Why post-deploy (not UserData): UserData cannot be retried without
# recreating the instance, and failures are invisible to CloudFormation.
# SSM Run Command gives us exit codes, CloudWatch logs, and idempotent re-runs.
#
# Usage:
#   ./infrastructure/scripts/bootstrap.sh
#   LLAMA_FACTORY_REF=v0.9.1 ./infrastructure/scripts/bootstrap.sh
#   STACK_NAME=... AWS_REGION=... ./infrastructure/scripts/bootstrap.sh
#
# Env vars:
#   STACK_NAME         (default: emotion-companion-dev)
#   AWS_REGION         (default: us-west-2)
#   LLAMA_FACTORY_REF  (default: use stack parameter; override for pinning)
#   WAIT               (default: true; set 'false' to return immediately)

set -euo pipefail

STACK_NAME="${STACK_NAME:-emotion-companion-dev}"
AWS_REGION="${AWS_REGION:-us-west-2}"
LLAMA_FACTORY_REF="${LLAMA_FACTORY_REF:-}"
WAIT="${WAIT:-true}"

# ---- Look up stack outputs -------------------------------------------------
lookup() {
  aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" \
    --output text
}

INSTANCE_ID="$(lookup InstanceId)"
DOC_NAME="$(lookup BootstrapDocumentName)"

if [ -z "$INSTANCE_ID" ] || [ "$INSTANCE_ID" = "None" ]; then
  echo "ERROR: could not find InstanceId output on stack $STACK_NAME." >&2
  exit 1
fi
if [ -z "$DOC_NAME" ] || [ "$DOC_NAME" = "None" ]; then
  echo "ERROR: could not find BootstrapDocumentName on stack $STACK_NAME." >&2
  exit 1
fi

# ---- Wait for the instance to be SSM-reachable -----------------------------
echo "Checking SSM connectivity to $INSTANCE_ID ..."
for attempt in $(seq 1 30); do
  PING="$(aws ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query 'InstanceInformationList[0].PingStatus' \
    --output text 2>/dev/null || echo None)"
  if [ "$PING" = "Online" ]; then
    echo "  instance is SSM-online."
    break
  fi
  if [ "$attempt" -eq 30 ]; then
    echo "ERROR: instance never became SSM-online after 5 minutes." >&2
    exit 1
  fi
  sleep 10
done

# ---- Wait for UserData marker (means CloudWatch agent etc. are up) ---------
echo "Checking UserData marker ..."
MARKER_OUT="$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name AWS-RunShellScript \
  --parameters 'commands=["test -f /var/lib/cloud/instance/userdata-complete && echo READY || echo PENDING"]' \
  --region "$AWS_REGION" --output json \
  --query 'Command.CommandId' --output text)"
sleep 5
for _ in 1 2 3 4 5 6; do
  RESULT="$(aws ssm get-command-invocation \
    --command-id "$MARKER_OUT" --instance-id "$INSTANCE_ID" \
    --region "$AWS_REGION" --query 'StandardOutputContent' --output text 2>/dev/null || echo '')"
  if echo "$RESULT" | grep -q READY; then
    echo "  UserData marker present."
    break
  fi
  sleep 10
done

# ---- Send the bootstrap command --------------------------------------------
PARAMS='{"commands":["echo starting"]}'
if [ -n "$LLAMA_FACTORY_REF" ]; then
  PARAMS=$(printf '{"LlamaFactoryRef":["%s"]}' "$LLAMA_FACTORY_REF")
fi

echo "Sending SSM command: $DOC_NAME"
echo "  instance:           $INSTANCE_ID"
echo "  llama_factory_ref:  ${LLAMA_FACTORY_REF:-<stack default>}"
echo "  region:             $AWS_REGION"
echo "  log group:          /aws/ssm/$DOC_NAME"

# shellcheck disable=SC2046  # intentional: conditional --parameters arg
CMD_ID="$(aws ssm send-command \
  --document-name "$DOC_NAME" \
  --targets "Key=instanceids,Values=$INSTANCE_ID" \
  --region "$AWS_REGION" \
  --cloud-watch-output-config "CloudWatchLogGroupName=/aws/ssm/$DOC_NAME,CloudWatchOutputEnabled=true" \
  --timeout-seconds 3600 \
  $( [ -n "$LLAMA_FACTORY_REF" ] && echo "--parameters" && echo "$PARAMS" ) \
  --query 'Command.CommandId' --output text)"

echo
echo "Command ID: $CMD_ID"
echo "Stream logs with:"
echo "  aws logs tail /aws/ssm/$DOC_NAME --follow --region $AWS_REGION"
echo "Inspect status with:"
echo "  aws ssm list-command-invocations --command-id $CMD_ID --details --region $AWS_REGION"

if [ "$WAIT" != "true" ]; then
  exit 0
fi

# ---- Poll until complete ---------------------------------------------------
echo
echo "Waiting for command to finish (this takes ~10-20 min for first run)..."
while true; do
  STATUS="$(aws ssm list-command-invocations \
    --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query 'CommandInvocations[0].Status' --output text)"
  case "$STATUS" in
    Success)
      echo "Bootstrap complete."
      exit 0
      ;;
    Failed|Cancelled|TimedOut)
      echo "Bootstrap ended with status: $STATUS" >&2
      aws ssm list-command-invocations \
        --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --details \
        --region "$AWS_REGION" \
        --query 'CommandInvocations[0].CommandPlugins[*].[Name,Status,Output]' \
        --output table >&2 || true
      exit 1
      ;;
    InProgress|Pending|Delayed)
      printf "  status: %s\r" "$STATUS"
      sleep 20
      ;;
    *)
      echo "Unexpected status: $STATUS"
      sleep 20
      ;;
  esac
done
