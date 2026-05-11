# ADR-0007: Training-stack bootstrap via SSM Document, not UserData

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author

## Context

We need to install a non-trivial training stack on the EC2 instance:

- `uv`
- LLaMA-Factory (cloned from git at a pinned commit)
- Unsloth
- vLLM (separate venv)

These installs involve network downloads, CUDA-version-sensitive pip builds,
and occasional upstream breakage. Prior experience with CDK/CFN UserData has
surfaced three problems:

1. UserData **cannot be retried** without recreating the instance. A single
   pip 502 on a new day's run forces `aws cloudformation delete-stack` +
   `create-stack` — ~10 minutes of wasted time for a transient error
2. UserData **failures are invisible to CloudFormation**. With `set -e`, the
   bash script exits non-zero, but the instance still reaches `running` and
   the stack reaches `CREATE_COMPLETE`. You discover the problem at the next
   interactive shell session, not at deploy time
3. UserData **output** ends up in `/var/log/cloud-init-output.log` on the
   instance; you have to SSM in to read it. No CloudWatch Logs integration
   out of the box for UserData

## Decision

Split instance startup into **two phases**:

- **Phase 1 (UserData)** — minimal, very-hard-to-fail bootstrap:
  CloudWatch agent, `/etc/profile.d/project.sh` env vars, auto-shutdown cron,
  a `userdata-complete` marker file. No pip installs, no git clones
- **Phase 2 (SSM Document + `make bootstrap`)** — the fragile work:
  install uv, build train/serve venvs, clone LLaMA-Factory at a pinned commit,
  install training and serving dependencies

The SSM Document is declared in the same CloudFormation stack as the instance
(`AWS::SSM::Document`). The operator triggers it from their Mac via
`make bootstrap`, which calls `aws ssm send-command`.

## Consequences

Good:

- Bootstrap is **idempotent and retryable** — `make bootstrap` again on
  failure, no need to destroy the instance. Each SSM Document step checks
  for pre-existing state (`[ -d ~/venv-train ] || uv venv ...`)
- **Structured output**: every step has a name, exit code, stdout, stderr;
  `aws ssm list-command-invocations --details` shows them in a table
- **CloudWatch Logs** integration: `/aws/ssm/<doc-name>` holds all output,
  tailable with `aws logs tail --follow`. Log retention 30 days
- **LLaMA-Factory can be re-pinned** without touching the instance:
  `LLAMA_FACTORY_REF=<commit> make bootstrap` updates and rebuilds
- **Clean separation**: CFN owns the instance; the SSM Document owns the
  software layer. Future migration to pre-baked AMI (Packer) replaces
  Phase 2 with Phase 0 without changing Phase 1

Bad / watch-outs:

- Two commands instead of one (`make deploy` then `make bootstrap`). Mitigated
  by making `make bootstrap` idempotent so operators can freely re-run
- The SSM Document is YAML-inside-YAML, which makes quoting tedious. Each
  command line that uses bash variables has to escape `$` for CloudFormation
  and quote inner double quotes. Reviewers should copy the step into a
  standalone `.sh` file to read it, not try to parse it in-template
- `aws ssm send-command` requires the instance to be SSM-Online, which needs
  a 30-60 second gap after deploy completes. Our `bootstrap.sh` polls for
  `PingStatus=Online` before sending

## Alternatives considered

| Option | Why rejected |
|---|---|
| All installs in UserData | The original design; falls over on first transient pip error with no recovery path |
| Packer pre-baked AMI | The correct long-term answer but too heavy for PoC. Requires building a Packer pipeline, maintaining an AMI registry, and paying per-AMI storage. Plan to migrate once Phase 2 is stable |
| CloudFormation Init (`cfn-init`) | Older pattern; tightly couples install logic to CFN Metadata; no structured retry story beyond `cfn-signal`. SSM Document is the modern equivalent |
| Custom Resource / Lambda | Overkill for "run a shell script on the instance"; adds an IAM role, a Lambda, and an SNS topic for a problem SSM solves natively |
| Docker container on instance | Reasonable; defers complex install to image build. For PoC, the user wants `llamafactory-cli` directly on the host without an extra container layer. Revisit once training-stack stabilizes |

## References

- SSM Document docs: https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-ssm-docs.html
- `AWS::SSM::Document` CFN: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-ssm-document.html
