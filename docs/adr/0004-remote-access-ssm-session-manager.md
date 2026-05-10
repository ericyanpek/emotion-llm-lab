# ADR-0004: Remote access via AWS SSM Session Manager (zero public ports)

- **Status:** Accepted
- **Date:** 2026-05-10
- **Deciders:** project PoC author

## Context

Training runs on a remote GPU EC2 instance; developers work from a MacBook.
We need:

- Interactive shell for ad-hoc operations
- Port forwarding for the LLaMA-Factory web UI (7860), TensorBoard (6006),
  and vLLM (8000)
- Audit trail of who accessed the instance
- Minimal attack surface (we will eventually store pre-release model
  weights, persona docs, and potentially PII-redacted training data)

The naive pattern — SSH over port 22 with a keypair — exposes an inbound port
and requires key distribution and rotation.

## Decision

Use **AWS SSM Session Manager** for all remote access:

- Interactive shell: `aws ssm start-session --target <iid>`
- Port forwarding: `aws ssm start-session --document-name AWS-StartPortForwardingSession`
- EC2 Security Group: **zero inbound rules**. Egress scoped to 443/80/53/123

Adopted directly from the OpenClaw-on-Bedrock AWS sample's security baseline.

## Consequences

Good:

- No inbound ports on the training instance — SSH brute-force attempts and
  accidental public exposure of Gradio UI become impossible
- IAM-based authentication replaces SSH key management; temporary STS
  credentials, MFA, role assumption all work out of the box
- Every session logged in CloudTrail; keystrokes can optionally be streamed
  to CloudWatch / S3 for compliance
- Instance can run in a private subnet with VPC endpoints for SSM
  (upgrade path to prod posture — documented, not enabled for PoC)

Bad / watch-outs:

- Requires the Session Manager Plugin on the developer's Mac
  (`brew install --cask session-manager-plugin`)
- The EC2 IAM role must carry `AmazonSSMManagedInstanceCore`; missing it
  produces a confusing "not a managed instance" error
- SSM port forwarding has per-connection overhead; bulk data transfer
  (datasets, checkpoints) still goes through S3 rather than the tunnel
- In environments where IAM is tightly governed, on-call engineers might
  not have `ssm:StartSession` permission — brief them ahead of incidents

## Alternatives considered

| Option | Why rejected |
|---|---|
| SSH with public key, SG 22 from allowed CIDR | Keys to distribute, rotate; public port remains an attack surface; no built-in audit |
| AWS Client VPN | $0.10/hr endpoint + $0.05/hr per connection, and still need a bastion or direct ENI access; overkill for single-developer PoC |
| Tailscale / Zerotier | Good for team internal networks; pulls a third-party control plane into the security boundary |
| Bastion host + private subnet | Adds a second instance to pay for and patch; SSM delivers the equivalent isolation natively |

## References

- OpenClaw-on-Bedrock SSM pattern: https://github.com/aws-samples/sample-OpenClaw-on-AWS-with-Bedrock
- AWS docs: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html
