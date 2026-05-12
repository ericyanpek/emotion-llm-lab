# ADR-0010: Secrets pass through env vars only, never baked into scripts

- **Status:** Accepted
- **Date:** 2026-05-11
- **Deciders:** project PoC author
- **Triggered by incident:** Hugging Face token leaked to the EC2 filesystem
  and AWS CloudWatch Logs on 2026-05-11; token was revoked and rotated the
  same day

## Context

During the first real SFT smoke test we leaked the Hugging Face read token
along three vectors:

1. **`set -x` in the bash runner** — every `export HF_TOKEN=hf_...` line was
   traced to stdout, which `tee` persisted in `/tmp/smoke.log`
2. **`$(aws ssm get-parameter ...)` evaluated at the wrong shell scope** —
   when the runner script was constructed via `cat > /home/ubuntu/run-smoke.sh
   <<EOS ... $(aws ssm get-parameter ...) ... EOS` inside an SSM payload, the
   command substitution executed **on the Mac at payload-construction time**
   rather than on the instance at script-execution time, baking the literal
   token value into the script file on disk
3. **AWS SSM Run Command CloudWatch Logs** — SSM agent captured every command
   and its stdout/stderr into `/aws/ssm/<doc>` log groups with default 30-day
   retention. The leaked stdout from (1) and the leaked file content from (2)
   both wound up in this group

Both (1) and (2) left the token in places where a CloudTrail-authorized
IAM principal could read it, even after we removed it from disk. Only
revoking the token at Hugging Face made the incident terminal.

## Decision

Three absolute rules for any script or SSM Document command that handles
secrets (HF tokens, W&B keys, OpenAI/Anthropic keys, AWS access keys,
database passwords, etc.):

### Rule 1 — No tracing

`set -x` is banned in any script that reads or exports a secret. Our
runners use `set -euo pipefail` only. When debugging, add `set -x` locally
for the *specific section* you need to trace and `set +x` immediately after,
never at script top.

### Rule 2 — Secret substitution must happen at the script's own shell scope

Command substitution (`$(...)`) or parameter expansion (`${VAR}`) involving
a secret must appear **inside** a versioned script that executes on the
target host. The exact pattern we use:

```bash
# Good: the substitution runs on the instance when the script is invoked.
HF_TOKEN=$(aws ssm get-parameter \
  --name /emotion-companion/dev/hf-token \
  --with-decryption \
  --query Parameter.Value --output text --region us-east-1)
export HF_TOKEN
```

```bash
# BAD: when this line is embedded inside a `cat <<EOS` heredoc constructed
# in a parent shell (e.g. an SSM send-command payload on the Mac), the
# $(...) evaluates in the PARENT shell, baking the resolved token into
# the heredoc body before the target file is written.
cat > run.sh <<EOS
HF_TOKEN=$(aws ssm get-parameter ...)   # <-- do NOT do this
EOS
```

When a runner script needs secrets, **commit the script to the repo** and
have the instance `git pull` it, rather than synthesizing the script at
send time from a payload string. See `scripts/run-smoke.sh` and
`scripts/run-dpo-smoke.sh` for the canonical pattern.

### Rule 3 — Secrets never land on disk under our control

Secrets live only in memory while a process runs. They never get written
to `.env`, `.aws/credentials`, `config.json`, tmux socket files, command
history, or similar. The only exception is AWS-managed SecureString in
SSM Parameter Store (encrypted at rest, access logged in CloudTrail).

When a secret *must* be passed to a child process, use:

- environment variables — inherited by forks, never in `ps` output on Linux
- `stdin` — e.g. `curl --netrc-file <(printf 'default password %s' "$token") ...`

Never:

- command-line arguments (appear in `ps -ef` on the instance)
- temporary files (hard to guarantee shredded)
- echoed to stdout/stderr (caught by SSM, CloudWatch, tmux log, tee)

## Consequences

Good:

- **Blast radius of a bug becomes small.** A buggy script that fails halfway
  no longer persists a token in a half-written `/tmp/something.sh`
- **CloudWatch Logs stays safe to retain.** Rule 1 in particular means the
  agent-captured command logs can be kept for audit without being a
  secret store
- **Git history stays clean** because secrets never live in files we commit

Bad / watch-outs:

- **Local debugging is slightly more annoying** — `set -x` at the top of a
  runner is a common first move when something's off. Reviewers must notice
  this in PRs. The pre-commit hook below fails CI on `set -[-A-Za-z]*x` in
  scripts under `scripts/` and `infrastructure/scripts/`
- **SSM send-command payloads are harder to write** — you can't just
  embed a secret-reading snippet inline. Instead, commit the runner and
  trigger it: `sudo -iu ubuntu bash /home/ubuntu/emotion-llm-lab/scripts/runner.sh`
- **Team onboarding requires reading this ADR** before people reach for
  the easy-looking bad patterns

## Alternatives considered

| Option | Why rejected |
|---|---|
| Trust developers' judgment case-by-case | The whole incident happened with careful developers "just trying to get a smoke test running". Humans lose to the path of least friction; we need a wall |
| Redact secret patterns post-hoc in CloudWatch | AWS does not offer log-event-level redaction; you can only delete whole log streams. By the time you notice the leak, the window for copy has already been open |
| Use AWS Secrets Manager secret-version rotation tied to training runs | Appropriate for production; for a PoC, over-engineered. The real fix is "don't leak in the first place", not "rotate weekly and hope" |
| gitleaks on pre-commit | Catches committed secrets, not runtime leaks. Still good to have (already configured in CI; see ADR-0007 note); this ADR is orthogonal — it prevents runtime leaks that never reach git |

## References

- HF token rotation: https://huggingface.co/settings/tokens (Invalidate → Regenerate)
- AWS SSM Parameter Store SecureString: https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-securestring.html
- CloudWatch Logs lifecycle: log streams can be deleted, individual events cannot be edited
- Incident timeline + cleanup: `docs/runbooks/first-deploy.md` "Secrets handling" section
