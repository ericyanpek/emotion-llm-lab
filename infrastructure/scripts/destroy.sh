#!/usr/bin/env bash
# destroy.sh — Tear down the training-env stack.
#
# NOTE: The S3 buckets (ArtifactBucket, AccessLogBucket) use DeletionPolicy:
# Retain — they will survive stack deletion. Empty and delete them manually
# if you want a full teardown:
#
#   aws s3 rb s3://<artifact-bucket> --force
#   aws s3 rb s3://<accesslog-bucket> --force
#
# Usage:
#   ./infrastructure/scripts/destroy.sh
#   STACK_NAME=emotion-companion-dev AWS_REGION=us-east-1 ./infrastructure/scripts/destroy.sh

set -euo pipefail

STACK_NAME="${STACK_NAME:-emotion-companion-dev}"
AWS_REGION="${AWS_REGION:-us-east-1}"

echo "About to delete stack: $STACK_NAME (region $AWS_REGION)"
read -rp "Are you sure? Type the stack name to confirm: " CONFIRM
if [ "$CONFIRM" != "$STACK_NAME" ]; then
  echo "Aborted."
  exit 1
fi

aws cloudformation delete-stack \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION"

echo "Delete initiated. Waiting for completion..."
aws cloudformation wait stack-delete-complete \
  --stack-name "$STACK_NAME" \
  --region "$AWS_REGION"

echo "Stack $STACK_NAME deleted."
echo
echo "Reminder: S3 buckets with DeletionPolicy: Retain survive stack deletion."
echo "List them with:"
echo "  aws s3 ls | grep emotion-companion"
