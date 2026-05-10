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
#   AWS_REGION          (default: us-east-1)
#   PROJECT_NAME        (default: emotion-companion)
#   ENVIRONMENT         (default: dev)
#   INSTANCE_TYPE       (default: g5.2xlarge)
#   USE_SPOT            (default: false)
#   ROOT_VOLUME_GB      (default: 500)
#   AUTO_SHUTDOWN_HOURS (default: 1)
#   BUDGET_LIMIT_USD    (default: 200)
#   BUDGET_EMAIL        (default: empty - no budget alarm)
#   VPC_ID              (default: auto-detected default VPC)
#   SUBNET_ID           (default: first public subnet in VPC in supported AZ)

set -euo pipefail

STACK_NAME="${STACK_NAME:-emotion-companion-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="${PROJECT_NAME:-emotion-companion}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g5.2xlarge}"
USE_SPOT="${USE_SPOT:-false}"
ROOT_VOLUME_GB="${ROOT_VOLUME_GB:-500}"
AUTO_SHUTDOWN_HOURS="${AUTO_SHUTDOWN_HOURS:-1}"
BUDGET_LIMIT_USD="${BUDGET_LIMIT_USD:-200}"
BUDGET_EMAIL="${BUDGET_EMAIL:-}"
VPC_ID="${VPC_ID:-}"
SUBNET_ID="${SUBNET_ID:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/../cloudformation/training-env.yaml"

if [ ! -f "$TEMPLATE" ]; then
  echo "ERROR: template not found at $TEMPLATE" >&2
  exit 1
fi

# ---- Preflight -------------------------------------------------------------
# Unless SKIP_PREFLIGHT=1, run the same checks the user would run manually.
# This surfaces quota/permission/name-collision issues in 30 seconds instead
# of 5 minutes of CFN rollback.
if [ "${SKIP_PREFLIGHT:-0}" != "1" ]; then
  PREFLIGHT="${SCRIPT_DIR}/preflight.sh"
  if [ -x "$PREFLIGHT" ]; then
    echo "--- Running preflight checks (set SKIP_PREFLIGHT=1 to skip) ---"
    if ! "$PREFLIGHT"; then
      echo
      echo "ERROR: preflight failed. Fix the issues above, or set SKIP_PREFLIGHT=1 to proceed anyway." >&2
      exit 1
    fi
    echo
  fi
fi

# ---- VPC/Subnet auto-detect (BYO networking) -------------------------------
# If caller didn't pass VPC_ID/SUBNET_ID, pick the default VPC and the first
# subnet in a g5-compatible AZ that maps public IPs on launch.
if [ -z "$VPC_ID" ]; then
  VPC_ID="$(aws ec2 describe-vpcs \
    --filters Name=isDefault,Values=true \
    --region "$AWS_REGION" \
    --query 'Vpcs[0].VpcId' --output text 2>/dev/null || true)"
  if [ -z "$VPC_ID" ] || [ "$VPC_ID" = "None" ]; then
    echo "ERROR: could not find a default VPC in $AWS_REGION." >&2
    echo "       Pass VPC_ID=vpc-... and SUBNET_ID=subnet-... explicitly." >&2
    exit 1
  fi
  echo "Auto-detected default VPC: $VPC_ID"
fi

if [ -z "$SUBNET_ID" ]; then
  # AZs that offer the chosen instance type.
  OFFERED_AZS="$(aws ec2 describe-instance-type-offerings \
    --location-type availability-zone \
    --filters "Name=instance-type,Values=$INSTANCE_TYPE" \
    --region "$AWS_REGION" \
    --query 'InstanceTypeOfferings[].Location' --output text 2>/dev/null || echo "")"
  if [ -z "$OFFERED_AZS" ]; then
    echo "ERROR: $INSTANCE_TYPE not offered in any AZ of $AWS_REGION." >&2
    exit 1
  fi
  # Build a comma-separated filter from space-separated AZs.
  AZ_FILTER="$(echo "$OFFERED_AZS" | tr '\t' ',' | tr ' ' ',')"
  SUBNET_ID="$(aws ec2 describe-subnets \
    --filters Name=vpc-id,Values="$VPC_ID" \
              Name=default-for-az,Values=true \
              "Name=availability-zone,Values=$AZ_FILTER" \
    --region "$AWS_REGION" \
    --query 'Subnets[0].SubnetId' --output text 2>/dev/null || true)"
  # Fallback: any subnet in a compatible AZ.
  if [ -z "$SUBNET_ID" ] || [ "$SUBNET_ID" = "None" ]; then
    SUBNET_ID="$(aws ec2 describe-subnets \
      --filters Name=vpc-id,Values="$VPC_ID" \
                "Name=availability-zone,Values=$AZ_FILTER" \
      --region "$AWS_REGION" \
      --query 'Subnets[0].SubnetId' --output text 2>/dev/null || true)"
  fi
  if [ -z "$SUBNET_ID" ] || [ "$SUBNET_ID" = "None" ]; then
    echo "ERROR: no subnet in VPC $VPC_ID in a $INSTANCE_TYPE-compatible AZ." >&2
    exit 1
  fi
  echo "Auto-detected subnet: $SUBNET_ID"
fi

echo "=== Emotion Companion Training Env Deploy ==="
echo "Stack:         $STACK_NAME"
echo "Region:        $AWS_REGION"
echo "VPC / Subnet:  $VPC_ID / $SUBNET_ID"
echo "Instance:      $INSTANCE_TYPE ($( [ "$USE_SPOT" = "true" ] && echo "Spot" || echo "On-Demand" ))"
echo "Volume:        ${ROOT_VOLUME_GB}GB gp3"
echo "Auto-shutdown: ${AUTO_SHUTDOWN_HOURS}h idle (+ CloudWatch alarm)"
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
    VpcId="$VPC_ID" \
    SubnetId="$SUBNET_ID" \
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
