#!/usr/bin/env bash
# set-secrets.sh — Populate SSM Parameter Store secrets (HF token, Wandb key).
#
# Secrets are created by CFN as placeholder String values; this script
# overwrites them with SecureString values. Prompts interactively so the
# token never appears in shell history.
#
# Usage:
#   ./infrastructure/scripts/set-secrets.sh

set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-emotion-companion}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"

put_secret() {
  local name="$1"
  local prompt="$2"
  local path="/${PROJECT_NAME}/${ENVIRONMENT}/${name}"

  echo
  read -rs -p "$prompt (leave empty to skip): " value
  echo
  if [ -z "$value" ]; then
    echo "  skipped $path"
    return
  fi

  aws ssm put-parameter \
    --name "$path" \
    --value "$value" \
    --type SecureString \
    --overwrite \
    --region "$AWS_REGION" >/dev/null
  echo "  stored $path (SecureString)"
}

echo "Updating SSM parameters for project=$PROJECT_NAME env=$ENVIRONMENT region=$AWS_REGION"
put_secret "hf-token" "Hugging Face token (hf_...)"
put_secret "wandb-api-key" "Weights & Biases API key"

echo
echo "Done. The EC2 instance role has ssm:GetParameter access to /${PROJECT_NAME}/${ENVIRONMENT}/*"
