#!/usr/bin/env bash
# deploy.sh — Create or update the training-env CloudFormation stack.
#
# Usage:
#   ./infrastructure/scripts/deploy.sh              # uses defaults
#   AWS_REGION=us-east-1 ./infrastructure/scripts/deploy.sh
#   USE_SPOT=true ./infrastructure/scripts/deploy.sh
#   BUDGET_EMAIL=me@example.com ./infrastructure/scripts/deploy.sh
#
# Environment variables:
#   STACK_NAME          (default: emotion-companion-dev)
#   AWS_REGION          (default: us-west-2)
#   PROJECT_NAME        (default: emotion-companion)
#   ENVIRONMENT         (default: dev)
#   INSTANCE_TYPE       (default: g5.2xlarge)
#   USE_SPOT            (default: false)
#   ROOT_VOLUME_GB      (default: 500)
#   AUTO_SHUTDOWN_HOURS (default: 8)
#   BUDGET_LIMIT_USD    (default: 200)
#   BUDGET_EMAIL        (default: empty - no budget alarm)

set -euo pipefail

STACK_NAME="${STACK_NAME:-emotion-companion-dev}"
AWS_REGION="${AWS_REGION:-us-west-2}"
PROJECT_NAME="${PROJECT_NAME:-emotion-companion}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g5.2xlarge}"
USE_SPOT="${USE_SPOT:-false}"
ROOT_VOLUME_GB="${ROOT_VOLUME_GB:-500}"
AUTO_SHUTDOWN_HOURS="${AUTO_SHUTDOWN_HOURS:-8}"
BUDGET_LIMIT_USD="${BUDGET_LIMIT_USD:-200}"
BUDGET_EMAIL="${BUDGET_EMAIL:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/../cloudformation/training-env.yaml"

if [ ! -f "$TEMPLATE" ]; then
  echo "ERROR: template not found at $TEMPLATE" >&2
  exit 1
fi

echo "=== Emotion Companion Training Env Deploy ==="
echo "Stack:         $STACK_NAME"
echo "Region:        $AWS_REGION"
echo "Instance:      $INSTANCE_TYPE ($( [ "$USE_SPOT" = "true" ] && echo "Spot" || echo "On-Demand" ))"
echo "Volume:        ${ROOT_VOLUME_GB}GB gp3"
echo "Auto-shutdown: ${AUTO_SHUTDOWN_HOURS}h idle"
echo "Budget:        \$${BUDGET_LIMIT_USD}/mo $( [ -n "$BUDGET_EMAIL" ] && echo "→ $BUDGET_EMAIL" || echo "(no alerts)" )"
echo "==========================================="
echo

# Validate template first
echo "Validating template..."
aws cloudformation validate-template \
  --template-body "file://${TEMPLATE}" \
  --region "$AWS_REGION" >/dev/null

# Deploy (creates or updates).
aws cloudformation deploy \
  --stack-name "$STACK_NAME" \
  --template-file "$TEMPLATE" \
  --region "$AWS_REGION" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ProjectName="$PROJECT_NAME" \
    Environment="$ENVIRONMENT" \
    InstanceType="$INSTANCE_TYPE" \
    UseSpotInstance="$USE_SPOT" \
    RootVolumeSizeGB="$ROOT_VOLUME_GB" \
    AutoShutdownHours="$AUTO_SHUTDOWN_HOURS" \
    BudgetLimitUSD="$BUDGET_LIMIT_USD" \
    BudgetNotificationEmail="$BUDGET_EMAIL" \
  --tags Project="$PROJECT_NAME" Environment="$ENVIRONMENT"

echo
echo "=== Stack deployed. Outputs: ==="
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
  --output table

echo
echo "Next steps:"
echo "  1. Set your Hugging Face token:"
echo "     aws ssm put-parameter --name /${PROJECT_NAME}/${ENVIRONMENT}/hf-token \\"
echo "       --value <YOUR_HF_TOKEN> --type SecureString --overwrite --region $AWS_REGION"
echo
echo "  2. Connect via SSM tunnel:"
echo "     ./infrastructure/scripts/tunnel.sh"
echo
echo "  3. Or get an interactive shell:"
echo "     ./infrastructure/scripts/ssm-shell.sh"
