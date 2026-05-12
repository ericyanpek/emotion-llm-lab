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


## Lessons from the first real deploy (2026-05-10)

Keep this list close; each bullet is a failure we already debugged so you
don't have to.

### CFN rollout

- **Regional VPC quota (5 by default) is often saturated in shared accounts.**
  Our template therefore BYOs VPC/Subnet (default VPC when env vars unset)
  rather than creating its own. See [ADR](#) if we ever need to revert.
- **`AWS::SSM::Document` with a `Name:` cannot be updated in place** if the
  change requires replacement. Omit `Name` so CFN generates one; consumers
  read the doc name from the `BootstrapDocumentName` stack output.
- **SSM agent's UserData marker alone is not enough** — bootstrap.sh also
  polls `ssm describe-instance-information` for `PingStatus=Online`. An
  instance can be `running` in EC2 long before SSM picks it up.

### SSM Run Command

- **`/bin/sh` on Ubuntu is `dash`, which doesn't support `set -o pipefail`.**
  Every SSM Document step that uses bash-only features must start with
  `#!/bin/bash`. Silent failure on line 1 otherwise.
- **Truncated output in `get-command-invocation`**: when a step's output is
  long, use the CloudWatch log group (`/emotion-companion/dev/bootstrap`)
  to see the full stderr/stdout rather than the SSM API response.

### Python / torch / uv

- **LLaMA-Factory's `dependencies` lists `torch>=2.4.0` outright**, so you
  can't avoid installing torch into the venv, even with
  `--system-site-packages`. Plan for a self-contained train venv. See
  [ADR-0008](../adr/0008-train-venv-self-contained-torch.md).
- **`--extra-index-url` is per-command, not sticky.** For the cu128 wheel
  index to apply across all installs, export
  `UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu128` and
  `UV_INDEX_STRATEGY=unsafe-best-match` as env vars in every step.
- **Unsloth downgrades torch silently** to match its pre-compiled kernels
  (currently exactly `2.10.0+cu128`). Pin torch to match. See
  [ADR-0009](../adr/0009-unsloth-pins-torch-version.md).
- **`--no-build-isolation` requires every build backend pre-seeded in the
  venv**. LLaMA-Factory needs `hatchling` AND `editables`; only seeding
  hatchling yields `ModuleNotFoundError: editables`.
- **LLaMA-Factory v0.9.4 doesn't expose `bitsandbytes` as an extra**
  despite README references. Install `bitsandbytes` as a separate
  `uv pip install`, not via `.[bitsandbytes]`.
- **LLaMA-Factory cpp-extension warning "Please upgrade to torch >= 2.11.0"**
  is expected given our Unsloth pin at 2.10.0. Training works; we accept
  the minor perf trade for Unsloth's 2x speedup.


### Starting LLaMA-Factory webui

Once bootstrap is green, start the webui from your Mac via a single SSM
command, then tunnel to it:

```bash
# On the instance, in a detached tmux session (survives SSM disconnect):
aws ssm send-command --instance-ids <i-...> --document-name AWS-RunShellScript \
  --region us-east-1 --parameters 'commands=[
    "sudo -iu ubuntu bash -c \"tmux new-session -d -s webui /home/ubuntu/start-webui.sh\""
  ]'

# Mac side: tunnel (defaults to 7860/6006/8000)
make tunnel

# Browser:
open http://localhost:7860
```

### Three more pitfalls you'll hit after bootstrap succeeds

- **`sudo -u ubuntu` vs `sudo -iu ubuntu`**: the former keeps root's HOME
  and `/tmp/tmux-0/` path, so tmux under it can't find its server socket
  (`error connecting to /tmp/tmux-0/default`). Always use `-i` (login shell)
  for anything that needs ubuntu's real environment, including tmux and
  anything that reads `~/.bashrc`.
- **`AWS-StartPortForwardingSession` accepts exactly ONE port per session**,
  despite the old docs showing arrays. Our tunnel.sh spawns one subprocess
  per port and traps SIGINT to clean all up. Passing three-element
  `["7860","6006","8000"]` fails with `InvalidParameters`.
- **Unsloth violates LLaMA-Factory's declared upper bounds at runtime**.
  After `uv pip install unsloth`, `check_dependencies()` in
  `llamafactory/extras/misc.py` raises ImportError because datasets, peft,
  etc. are now too new. The SSM Document re-pins them immediately after
  the unsloth install; keep that pin list synced with the bounds in that
  misc.py file on every `llama_factory_ref` bump.


## Secrets handling

The SFT smoke run on 2026-05-11 leaked a Hugging Face token through a
combination of `set -x` tracing and an `$(aws ssm get-parameter ...)` that
evaluated in the wrong shell scope, ending up in `/tmp/smoke.log`,
`/home/ubuntu/run-smoke.sh` on disk, and the `/emotion-companion/dev/ssm-agent`
CloudWatch Logs group. The token was revoked and rotated the same day.

[ADR-0010](../adr/0010-secrets-never-baked-into-scripts.md) codifies three
rules to prevent a recurrence. The minimum you need to remember:

- **Never use `set -x`** in any script that touches a secret. Our runners
  use `set -euo pipefail` and add `set -x` / `set +x` around specific
  blocks only when actively debugging
- **Never embed `$(aws ssm get-parameter ...)` inside a heredoc** that a
  parent shell constructs — the substitution runs in the parent, baking
  the secret into the child script literally. Commit the runner and
  trigger it instead; see `scripts/run-smoke.sh` for the canonical pattern
- **Secrets live only in environment variables while a process runs** —
  never in files you write, command-line args, or stdout

### If a secret leaks

1. **Revoke first, clean up second.** In HF → Settings → Tokens → Invalidate
   the suspect token. AWS keys → IAM console → Deactivate. The CloudWatch
   traces become harmless once the token is dead
2. Rotate: create a fresh token, `make secrets`, restart whatever needs it
3. Delete affected CloudWatch log streams:
   ```bash
   aws logs delete-log-stream --log-group-name <group> --log-stream-name <stream>
   ```
4. On the instance, truncate `/var/log/amazon/ssm/amazon-ssm-agent.log`,
   clear bash history (`rm ~/.bash_history`), and remove any `/tmp/*.log`
   or orchestration JSON that captured the secret
5. Note: the `grep hf_xxx` commands used to hunt for leaks themselves get
   logged by sudo/journald. That's fine — they only contain the search
   substring, not the full token, and the token is now dead
