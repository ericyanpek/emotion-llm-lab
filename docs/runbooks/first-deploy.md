# Runbook: First deploy

Linear path from an empty account to an instance you can SSM into with the
training stack installed.

## Happy path (5 commands, ~25 min total)

```bash
# 1. Preflight — 30 sec; bails out early if anything is missing
make preflight

# 2. Create the stack — 5-8 min; EC2 + networking + S3 + SSM Doc
make deploy

# 3. Set your Hugging Face token — interactive, goes to SSM Parameter Store
make secrets

# 4. Install the training stack on the instance — 10-20 min, streamed
make bootstrap

# 5. Open the SSM tunnel — keep this terminal running
make tunnel
```

Then in a browser: `http://localhost:7860` → LLaMA-Factory web UI.

## What to do when each step fails

### Preflight failures

| Symptom | Fix |
|---|---|
| `aws sts get-caller-identity failed` | Re-run `aws configure` or check `AWS_PROFILE` |
| `On-Demand G/VT quota: 0 vCPU` | [Request quota increase](https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas/L-DB2E81BA) for the target region. Usually approved within 24-48 h |
| `DLAMI SSM parameter did not resolve` | IAM principal lacks `ssm:GetParameter` on the public AWS path. Add the permission or use a different principal |
| `Stack emotion-companion-dev is in ROLLBACK_COMPLETE` | `make destroy` then retry |
| `S3 bucket [...] already exists in this account but no stack — orphan` | `aws s3 rb s3://<name> --force` (after confirming nothing important inside) |
| `S3 bucket name [...] taken by another account` | Change `PROJECT_NAME` or `ENVIRONMENT` env var to make the bucket name unique |

### `make deploy` fails (CloudFormation rollback)

1. Find the root cause — first failed resource in the stack events:
   ```bash
   aws cloudformation describe-stack-events --stack-name emotion-companion-dev \
     --query 'StackEvents[?ResourceStatus==`CREATE_FAILED`].[Timestamp,LogicalResourceId,ResourceStatusReason]' \
     --output table
   ```
2. Common causes:
   - `InsufficientInstanceCapacity` in the chosen AZ: rare in us-east-1; retry once, or force a different AZ by setting `SubnetCidr` and relaunching
   - `VcpuLimitExceeded`: preflight should have caught this; check you didn't switch region after preflight
   - `Name already exists` for IAM role / instance profile: usually a leftover from a half-destroyed previous stack; delete the named resource manually
3. After fixing the cause, `make destroy` to clear the rolled-back stack, then `make deploy` again.

### `make bootstrap` fails

Bootstrap is **idempotent** — just re-run. SSM re-uses the same instance; no
CloudFormation redeploy needed.

1. See which step failed:
   ```bash
   aws ssm list-command-invocations \
     --filters Key=DocumentName,Values=emotion-companion-dev-training-stack-bootstrap \
     --details --max-results 1 \
     --query 'CommandInvocations[0].CommandPlugins[*].[Name,Status,Output]' \
     --output table
   ```
2. Check CloudWatch logs:
   ```bash
   aws logs tail /aws/ssm/emotion-companion-dev-training-stack-bootstrap \
     --since 10m
   ```
3. Common causes:
   - pip 502 / HF Hub 503: transient network. `make bootstrap` again
   - torch / bitsandbytes build error: most often means `--system-site-packages` didn't work — confirm the instance booted from the DLAMI (`AMI_ID` in user-data log)
   - `git checkout <sha>` fails: the LLAMA_FACTORY_REF is invalid. Override: `LLAMA_FACTORY_REF=main make bootstrap`
4. Nuclear option: `make destroy` then redeploy. A fresh instance re-triggers `make bootstrap`.

### `make tunnel` fails

| Symptom | Fix |
|---|---|
| `session-manager-plugin not found` | `brew install --cask session-manager-plugin` |
| `TargetNotConnected` | Instance is stopped or still booting. Wait 30 sec and retry, or: `aws ec2 describe-instance-status --instance-ids <id>` |
| `AccessDeniedException on ssm:StartSession` | Your IAM principal is missing `ssm:StartSession` + `ssm:StartPortForwardingSession` on the target instance |
| Tunnel connects but `localhost:7860` shows nothing | LLaMA-Factory webui isn't running yet. SSM into the box and start it: `source ~/venv-train/bin/activate && llamafactory-cli webui` |

## Cost-aware shutdown

Always stop the instance when you're done for the day. EBS storage ($40/mo)
stays; GPU hours stop:

```bash
aws ec2 stop-instances --instance-ids "$(aws cloudformation describe-stacks \
  --stack-name emotion-companion-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' \
  --output text)"
```

Next day: start it, re-run `make tunnel`, resume. `make bootstrap` is idempotent
— no need to re-run it after a stop/start.

## Full teardown

```bash
make destroy
```

S3 buckets are **retained** on purpose (training artifacts survive a bad
`destroy`). To fully remove:

```bash
aws s3 rb s3://emotion-companion-dev-artifacts-<account>-us-east-1 --force
aws s3 rb s3://emotion-companion-dev-accesslogs-<account>-us-east-1 --force
```
