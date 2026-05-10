# Infrastructure

CloudFormation stack for a GPU training instance with **zero public ports**.
All access goes through AWS SSM Session Manager — same security baseline as
the [OpenClaw-on-Bedrock](https://github.com/aws-samples/sample-OpenClaw-on-AWS-with-Bedrock)
reference architecture.

## What gets deployed

```
VPC (10.42.0.0/16)
└── public subnet
    └── EC2 g5.2xlarge (A10G 24GB, DLAMI PyTorch 2.7)
        ├── IAM role → SSM + S3 artifacts + Parameter Store read
        ├── EBS 500GB gp3 (encrypted)
        ├── IMDSv2 required
        └── SG: 0 inbound / scoped egress (443, 80, 53, 123 only)

S3
├── artifacts bucket       (datasets + LoRA adapters, SSE + versioning + TLS-only)
└── accesslogs bucket      (S3 access audit trail, 90-day retention)

SSM Parameter Store
├── /emotion-companion/dev/hf-token        (HF token, SecureString)
└── /emotion-companion/dev/wandb-api-key   (W&B key, SecureString)

AWS Budgets (optional)
└── monthly alert at 80% / 100% of limit
```

## Prerequisites

- AWS CLI v2 with credentials configured (`aws sts get-caller-identity` works)
- Session Manager Plugin on your Mac:
  ```bash
  brew install --cask session-manager-plugin
  ```
- Service quota for your target GPU instance in the chosen region.
  G5 instances often have a default quota of 0 — request a quota increase
  for `All G and VT Spot Instance Requests` (or On-Demand) ahead of time.

## Deploy

```bash
# defaults: us-west-2, g5.2xlarge on-demand, 500GB disk, $200 budget
./infrastructure/scripts/deploy.sh

# with spot and budget alerts
USE_SPOT=true BUDGET_EMAIL=you@example.com ./infrastructure/scripts/deploy.sh

# different region / size
AWS_REGION=us-east-1 INSTANCE_TYPE=g6.2xlarge ./infrastructure/scripts/deploy.sh
```

First deploy takes ~5 minutes for the stack, then another ~5-10 minutes for
the EC2 user-data to install LLaMA-Factory, Unsloth, and vLLM.

## After the stack is up

### 1. Store your secrets

```bash
./infrastructure/scripts/set-secrets.sh
```

This prompts for your Hugging Face token and (optionally) Weights & Biases
key, and writes them as SecureString parameters that the EC2 instance role
can read. Tokens never appear in shell history.

### 2. Open the SSM tunnel

```bash
./infrastructure/scripts/tunnel.sh
```

Keep this terminal open. In another terminal / your browser:

| Service | URL on Mac |
|---|---|
| LLaMA-Factory webui | http://localhost:7860 |
| TensorBoard | http://localhost:6006 |
| vLLM (post-training) | http://localhost:8000 |

### 3. Interactive shell

```bash
./infrastructure/scripts/ssm-shell.sh
```

Then `sudo su - ubuntu` to switch to the user with the PyTorch env. Use
`tmux new -s train` to keep training running across disconnects.

## Customization

All parameters are in the template's `Parameters` section and overridable
via environment variables to `deploy.sh`:

| Parameter | Env var | Default | Notes |
|---|---|---|---|
| `InstanceType` | `INSTANCE_TYPE` | `g5.2xlarge` | `g5.xlarge` / `g6.2xlarge` / `g6e.2xlarge` also supported |
| `UseSpotInstance` | `USE_SPOT` | `false` | Saves ~70%; tolerates interruption (LLaMA-Factory resumes) |
| `RootVolumeSizeGB` | `ROOT_VOLUME_GB` | `500` | 200-2000 |
| `AutoShutdownHours` | `AUTO_SHUTDOWN_HOURS` | `8` | 0 disables; checks GPU+CPU idle |
| `BudgetLimitUSD` | `BUDGET_LIMIT_USD` | `200` | Monthly |
| `BudgetNotificationEmail` | `BUDGET_EMAIL` | *(empty)* | Email for 80% / 100% alerts |

## Destroy

```bash
./infrastructure/scripts/destroy.sh
```

**Note:** S3 buckets use `DeletionPolicy: Retain`. Empty and remove them
manually if you want a full teardown — this is intentional so a slipped
`cdk destroy` or `delete-stack` cannot wipe your training artifacts.

## Security posture

Modeled on the OpenClaw reference; explicit choices:

| Control | Implementation |
|---|---|
| No public SSH | Security Group has **zero inbound rules**. Access only via SSM. |
| IMDSv2 required | `HttpTokens: required` in launch template metadata options. |
| EBS encrypted | `Encrypted: true` on root volume. |
| S3 public blocked | `PublicAccessBlockConfiguration` with all four options true. |
| S3 TLS required | Bucket policy `DenyInsecureTransport` on `aws:SecureTransport: false`. |
| S3 access logged | Separate `accesslogs` bucket with 90-day lifecycle. |
| Secrets off-disk | HF / Wandb tokens in SSM Parameter Store SecureString. |
| Scoped IAM | Instance role grants S3 access only to *its own* artifact bucket, SSM only to `/<project>/<env>/*`. |
| Scoped egress | SG egress restricted to 443/80/53/123 (not 0.0.0.0/0:*). |
| Cost guardrail | Budget alarm + auto-shutdown on idle. |

### Deliberately NOT enabled (document choices)

- **S3 Object Lock**: we need to overwrite adapter iterations during experiments.
- **S3 cross-region replication**: artifacts are reproducible from code + data,
  CRR adds ~2x storage cost without PoC value.
- **VPC Endpoints for SSM/S3**: would cost ~$22/mo and buy private-subnet
  posture. Since we have no inbound rules and outbound is port-scoped,
  the marginal security gain is small for PoC. **Upgrade to private subnet
  + VPC endpoints before going to staging/prod.**

## Validate before deploying changes

```bash
# Syntax + schema
~/.local/bin/cfn-lint infrastructure/cloudformation/training-env.yaml

# Security compliance (via Kiro's AWS IaC power)
# or install cfn-guard locally:
#   brew install cloudformation-guard
```

## Cost estimate (us-west-2, on-demand)

| Resource | Monthly |
|---|---|
| g5.2xlarge (8h/day, 20 days) | ~$190 |
| g5.2xlarge (24/7) | ~$880 |
| EBS 500GB gp3 | ~$40 |
| S3 (~50GB artifacts) | ~$1 |
| CloudWatch logs/metrics | ~$2 |
| **Typical PoC (8h×20d)** | **~$235** |

Always turn the instance **off** when not actively training:

```bash
aws ec2 stop-instances --instance-ids <id> --region <region>
```

(EBS still charged while stopped, GPU hours are not.)
