# Architecture Decision Records

ADRs capture significant architectural or tooling decisions, the context that
drove them, and the trade-offs accepted. They are **append-only**: when a
decision changes, write a new ADR that **supersedes** the old one rather than
editing history.

## Why bother

6 months from now you will look at this codebase and wonder "why Qwen3 and not
Llama 4?" "why SSM and not VPN?" "why uv and not poetry?". The ADR folder is
the answer. Future contributors (including future you) skim the index, read
the relevant ADR, and either understand the constraint or propose superseding
it with new evidence.

## Index

| ID | Status | Title |
|---|---|---|
| [0001](./0001-base-model-qwen3-8b.md) | Accepted | Base model: Qwen3-8B |
| [0002](./0002-fine-tune-framework-llama-factory.md) | Accepted | Fine-tune framework: LLaMA-Factory + Unsloth |
| [0003](./0003-training-hardware-ec2-g5-dlami.md) | Accepted | Training hardware: EC2 g5.2xlarge + DLAMI |
| [0004](./0004-remote-access-ssm-session-manager.md) | Accepted | Remote access: AWS SSM, zero public ports |
| [0005](./0005-python-311-uv-dependency-groups.md) | Accepted | Python 3.11 pinned, uv with PEP 735 dependency groups |
| [0006](./0006-alignment-method-sft-dpo-with-kto-optional.md) | Accepted | Alignment method: SFT + DPO (KTO path preserved) |
| [0007](./0007-bootstrap-via-ssm-document.md) | Accepted | Training-stack bootstrap via SSM Document, not UserData |
| [0008](./0008-train-venv-self-contained-torch.md) | Accepted | Train venv carries its own torch stack (partially supersedes 0005) |
| [0009](./0009-unsloth-pins-torch-version.md) | Accepted | Unsloth dictates the torch version (2.10.0+cu128) |

## Conventions

- File name: `NNNN-short-kebab-case-title.md` where `NNNN` is zero-padded to 4 digits
- Status: `Proposed` → `Accepted` → optionally `Superseded by NNNN` or `Deprecated`
- Keep it **short** — one page usually. The discussion belongs in PR review;
  the ADR is the residue.

## Template

See [`0000-adr-template.md`](./0000-adr-template.md) — copy, rename, fill in.

## When to write one

Write an ADR when:

- You picked a tool, model, or framework **from a non-obvious shortlist** (e.g. Qwen3 vs Llama 4)
- You traded off a dimension that will bite later if forgotten (e.g. Apache 2.0 matters for global launch)
- You adopted a pattern the team hasn't seen before (e.g. SSM port-forward instead of SSH)
- Future-you needs to know the "why" to decide whether to keep or change a thing

Don't write an ADR for:

- Micro code-style decisions (that's what ruff config is for)
- Temporary PoC spikes you intend to throw away
- Things that would be obvious from the code alone
