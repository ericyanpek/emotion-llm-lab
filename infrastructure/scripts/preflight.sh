#!/usr/bin/env bash
# preflight.sh — Check we can actually deploy before spending 5 minutes on
# CloudFormation just to discover a missing tool, a quota of 0, or a name
# conflict.
#
# Checks (each fails fast with a remediation hint):
#   - Local tools present: aws, session-manager-plugin, uv, cfn-lint, shellcheck
#   - AWS credentials work and return an identity
#   - Target region is an active AWS region
#   - G/VT on-demand vCPU quota >= 8 in the target region
#   - DLAMI SSM parameter resolves (confirms the AMI exists in region)
#   - No stack with the same name already exists (unless UPDATE ok)
#   - No S3 bucket with the artifact / accesslogs name exists (deterministic
#     bucket names include account + region, but paranoia is cheap)
#   - Optional: IAM permissions smoke test
#
# Exit codes:
#   0   all checks passed
#   1   one or more checks failed
#   2   aws cli / credentials issue (can't even start)
#
# Usage:
#   ./infrastructure/scripts/preflight.sh
#   AWS_REGION=us-east-1 ./infrastructure/scripts/preflight.sh
#   STRICT=1 ./infrastructure/scripts/preflight.sh   # also run IAM smoke test

set -uo pipefail

STACK_NAME="${STACK_NAME:-emotion-companion-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"
PROJECT_NAME="${PROJECT_NAME:-emotion-companion}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g5.2xlarge}"

# vCPU per instance type, for quota math. Keep simple case statement — macOS
# ships bash 3.2 which doesn't fully support declare -A with dotted keys.
vcpu_for_type() {
  case "$1" in
    g5.xlarge)       echo 4 ;;
    g5.2xlarge|g6.2xlarge|g6e.2xlarge) echo 8 ;;
    g5.4xlarge|g6.4xlarge|g6e.4xlarge) echo 16 ;;
    g5.8xlarge)      echo 32 ;;
    g5.16xlarge)     echo 64 ;;
    *) echo 8 ;;  # conservative default
  esac
}
REQUIRED_VCPU="$(vcpu_for_type "$INSTANCE_TYPE")"

PASS=0; WARN=0; FAIL=0
say()  { printf '  %s\n' "$1"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
section() { printf '\n\033[1m== %s ==\033[0m\n' "$1"; }

# ---------------------------------------------------------------------------
section "Local tools"
# ---------------------------------------------------------------------------
check_cmd() {
  local bin="$1" install_hint="$2"
  if command -v "$bin" >/dev/null 2>&1; then
    ok "$bin: $($bin --version 2>&1 | head -1 | tr -d '\n')"
  else
    bad "$bin is not installed. Install: $install_hint"
  fi
}
check_cmd aws "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
check_cmd session-manager-plugin "brew install --cask session-manager-plugin"
check_cmd uv "curl -LsSf https://astral.sh/uv/install.sh | sh"

# cfn-lint ships via ~/.local/bin when installed with pip --user
if [ -x "$HOME/.local/bin/cfn-lint" ]; then
  ok "cfn-lint: $("$HOME/.local/bin/cfn-lint" --version 2>&1 | head -1)"
elif command -v cfn-lint >/dev/null 2>&1; then
  ok "cfn-lint: $(cfn-lint --version 2>&1 | head -1)"
else
  warn "cfn-lint not installed (only needed for local template validation). Install: pip install --user cfn-lint"
fi

check_cmd shellcheck "brew install shellcheck"

# ---------------------------------------------------------------------------
section "AWS credentials & region"
# ---------------------------------------------------------------------------
if ! CALLER="$(aws sts get-caller-identity --output json 2>/dev/null)"; then
  bad "aws sts get-caller-identity failed — no valid credentials."
  say "Check: aws configure, or AWS_PROFILE, or SSO session."
  exit 2
fi
ACCOUNT="$(echo "$CALLER" | python3 -c "import json,sys;print(json.load(sys.stdin)['Account'])")"
ARN="$(echo "$CALLER"     | python3 -c "import json,sys;print(json.load(sys.stdin)['Arn'])")"
ok "Account: $ACCOUNT"
ok "Principal: $ARN"
ok "Target region: $AWS_REGION"

if ! aws ec2 describe-regions --region-names "$AWS_REGION" --region "$AWS_REGION" >/dev/null 2>&1; then
  bad "Region $AWS_REGION is not active for this account. Check target region spelling."
fi

# ---------------------------------------------------------------------------
section "GPU capacity ($INSTANCE_TYPE)"
# ---------------------------------------------------------------------------
OFFERED="$(aws ec2 describe-instance-type-offerings \
  --location-type region \
  --filters "Name=instance-type,Values=$INSTANCE_TYPE" \
  --region "$AWS_REGION" \
  --query 'InstanceTypeOfferings[0].InstanceType' --output text 2>/dev/null || echo "")"
if [ "$OFFERED" = "$INSTANCE_TYPE" ]; then
  ok "$INSTANCE_TYPE is offered in $AWS_REGION"
else
  bad "$INSTANCE_TYPE is NOT offered in $AWS_REGION. Try us-east-1 or us-west-2."
fi

# On-Demand G/VT vCPU quota (L-DB2E81BA).
QUOTA_OD="$(aws service-quotas get-service-quota \
  --service-code ec2 --quota-code L-DB2E81BA \
  --region "$AWS_REGION" \
  --query 'Quota.Value' --output text 2>/dev/null || echo 0)"
QUOTA_OD="${QUOTA_OD%.*}"
if [ "$QUOTA_OD" -ge "$REQUIRED_VCPU" ]; then
  ok "On-Demand G/VT quota: $QUOTA_OD vCPU (need $REQUIRED_VCPU for one $INSTANCE_TYPE)"
else
  bad "On-Demand G/VT quota: $QUOTA_OD vCPU (need $REQUIRED_VCPU)."
  say "Request increase: https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas/L-DB2E81BA"
fi

# Spot G/VT (informational — only matters if USE_SPOT=true).
QUOTA_SPOT="$(aws service-quotas get-service-quota \
  --service-code ec2 --quota-code L-3819A6DF \
  --region "$AWS_REGION" \
  --query 'Quota.Value' --output text 2>/dev/null || echo 0)"
QUOTA_SPOT="${QUOTA_SPOT%.*}"
if [ "$QUOTA_SPOT" -ge "$REQUIRED_VCPU" ]; then
  ok "Spot G/VT quota: $QUOTA_SPOT vCPU (informational; only needed if USE_SPOT=true)"
else
  warn "Spot G/VT quota: $QUOTA_SPOT vCPU (not enough for USE_SPOT=true)"
fi

# ---------------------------------------------------------------------------
section "VPC capacity"
# ---------------------------------------------------------------------------
# Each stack can BYO VPC (no new VPC created), but if the caller hasn't set
# VPC_ID we need at least the default VPC to exist. Warn (not fail) when the
# regional VPC quota is saturated because it still might work if the default
# VPC is present.
VPC_QUOTA="$(aws service-quotas get-service-quota \
  --service-code vpc --quota-code L-F678F1CE \
  --region "$AWS_REGION" \
  --query 'Quota.Value' --output text 2>/dev/null || echo 0)"
VPC_QUOTA="${VPC_QUOTA%.*}"
VPC_COUNT="$(aws ec2 describe-vpcs --region "$AWS_REGION" \
  --query 'length(Vpcs)' --output text 2>/dev/null || echo 0)"
DEFAULT_VPC="$(aws ec2 describe-vpcs \
  --filters Name=isDefault,Values=true \
  --region "$AWS_REGION" \
  --query 'Vpcs[0].VpcId' --output text 2>/dev/null || echo None)"

if [ "$DEFAULT_VPC" != "None" ] && [ -n "$DEFAULT_VPC" ]; then
  ok "Default VPC present: $DEFAULT_VPC (BYO networking will use this)"
else
  warn "No default VPC in $AWS_REGION — must pass VPC_ID / SUBNET_ID explicitly"
fi
if [ "$VPC_COUNT" -ge "$VPC_QUOTA" ]; then
  warn "VPC usage: $VPC_COUNT / $VPC_QUOTA (saturated; stack uses existing VPC so ok)"
else
  ok "VPC usage: $VPC_COUNT / $VPC_QUOTA"
fi

# ---------------------------------------------------------------------------
section "AMI & service endpoints"
# ---------------------------------------------------------------------------
DLAMI_PARAM="/aws/service/deeplearning/ami/x86_64/oss-nvidia-driver-gpu-pytorch-2.7-ubuntu-22.04/latest/ami-id"
AMI_ID="$(aws ssm get-parameter --name "$DLAMI_PARAM" --region "$AWS_REGION" \
  --query 'Parameter.Value' --output text 2>/dev/null || echo "")"
if [ -n "$AMI_ID" ] && [[ "$AMI_ID" =~ ^ami- ]]; then
  ok "DLAMI PyTorch 2.7 resolves to $AMI_ID"
else
  bad "DLAMI SSM parameter did not resolve. Check region or IAM ssm:GetParameter permission."
fi

# ---------------------------------------------------------------------------
section "Name collisions"
# ---------------------------------------------------------------------------
STACK_STATE="$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" --region "$AWS_REGION" \
  --query 'Stacks[0].StackStatus' --output text 2>/dev/null || echo NONE)"
case "$STACK_STATE" in
  NONE)
    ok "No existing stack named $STACK_NAME (will be created fresh)"
    ;;
  CREATE_COMPLETE|UPDATE_COMPLETE|UPDATE_ROLLBACK_COMPLETE)
    warn "Stack $STACK_NAME exists ($STACK_STATE) — deploy will perform an UPDATE"
    ;;
  ROLLBACK_COMPLETE|ROLLBACK_FAILED|CREATE_FAILED)
    bad "Stack $STACK_NAME is in $STACK_STATE — must delete before re-deploying: make destroy"
    ;;
  *)
    warn "Stack $STACK_NAME is in state $STACK_STATE (may be in progress)"
    ;;
esac

ARTIFACT_BUCKET="${PROJECT_NAME}-${ENVIRONMENT}-artifacts-${ACCOUNT}-${AWS_REGION}"
LOG_BUCKET="${PROJECT_NAME}-${ENVIRONMENT}-accesslogs-${ACCOUNT}-${AWS_REGION}"
for B in "$ARTIFACT_BUCKET" "$LOG_BUCKET"; do
  # head-bucket returns:
  #   exit 0   → bucket exists and we own it
  #   error "Not Found" / 404  → bucket name is free
  #   error "Forbidden" / 403  → bucket exists in another account
  # We deliberately don't use a pipe to grep because `set -o pipefail` would
  # make the whole pipeline inherit head-bucket's non-zero exit.
  HB_OUT="$(aws s3api head-bucket --bucket "$B" --region "$AWS_REGION" 2>&1)"
  HB_EXIT=$?
  if [ "$HB_EXIT" -eq 0 ]; then
    # Bucket exists and is in our account.
    if [ "$STACK_STATE" = "NONE" ]; then
      bad "S3 bucket $B already exists in this account but no stack — orphan from a deleted stack. Remove: aws s3 rb s3://$B --force"
    else
      ok "S3 bucket $B exists and is owned by this stack (retained bucket)"
    fi
  elif echo "$HB_OUT" | grep -q -E "Not Found|404|NoSuchBucket"; then
    ok "S3 bucket name available: $B"
  elif echo "$HB_OUT" | grep -q -E "Forbidden|403"; then
    bad "S3 bucket name $B taken by another account. Pick a different PROJECT_NAME/ENVIRONMENT."
  else
    warn "S3 bucket $B: unrecognized head-bucket response — $HB_OUT"
  fi
done

# ---------------------------------------------------------------------------
section "Optional: IAM smoke test (STRICT=1 to enable)"
# ---------------------------------------------------------------------------
if [ "${STRICT:-0}" = "1" ]; then
  # simulate-principal-policy requires iam:SimulatePrincipalPolicy; not all IAM
  # principals have it. Fall back to a soft notice if we can't.
  for ACTION in \
    "cloudformation:CreateStack" \
    "ec2:RunInstances" \
    "iam:CreateRole" \
    "ssm:SendCommand" \
    "s3:CreateBucket"
  do
    RESULT="$(aws iam simulate-principal-policy \
      --policy-source-arn "$ARN" \
      --action-names "$ACTION" \
      --query 'EvaluationResults[0].EvalDecision' --output text 2>/dev/null || echo unknown)"
    case "$RESULT" in
      allowed) ok "IAM: $ACTION allowed";;
      implicitDeny|explicitDeny|denied) bad "IAM: $ACTION DENIED";;
      *) warn "IAM: $ACTION — can't simulate (need iam:SimulatePrincipalPolicy)";;
    esac
  done
else
  say "skipped (set STRICT=1 to enable IAM simulate-principal-policy checks)"
fi

# ---------------------------------------------------------------------------
section "Summary"
# ---------------------------------------------------------------------------
printf "  passed: \033[32m%d\033[0m   warnings: \033[33m%d\033[0m   failed: \033[31m%d\033[0m\n" "$PASS" "$WARN" "$FAIL"

if [ "$FAIL" -eq 0 ]; then
  echo
  echo "Ready to deploy. Next:"
  echo "  ./infrastructure/scripts/deploy.sh"
  exit 0
else
  echo
  echo "Fix the failures above before running deploy."
  exit 1
fi
