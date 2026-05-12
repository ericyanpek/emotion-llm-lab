# Multi-agent collaboration (this project)

Specific path ownership for `emotion-llm-lab`. This is the project's
instantiation of the user-level steering files at
`~/.kiro/steering/multi-agent-collaboration.md` and
`~/.kiro/steering/adr-conventions.md`.

At the start of any Kiro / Claude Code session, if more than one agent will
be active, the agent invokes:

```
#multi-agent-collaboration I am Agent X
#adr-conventions
```

Where X is one of A / B / C / D (see below).

## Active roles

| Role | Agent | Job | Status |
|---|---|---|---|
| **A · Builder** | primary training agent | Training pipeline, infrastructure, persona/data schemas | Active |
| **B · Verifier** | eval agent | LLM-as-judge eval + drift probes | Active |
| **C · Documenter** | learning agent | Theory backfill + learning plan synced to ADRs | Active |
| **D · Analyst** | — | Training/eval result analysis, next-experiment proposals | Reserved — activate when first real DPO v1 run produces results |

## Path ownership

Read this table before you edit anything. If a path you want to touch isn't
listed, it is probably someone else's territory — check or ask.

### A · Builder (primary training agent)

Owns (writes, commits):

```
infrastructure/                          # CloudFormation + ops scripts
configs/sft_*.yaml                       # SFT training configs
configs/dpo_*.yaml                       # DPO training configs
data/sft/                                # SFT sample data
data/dpo/                                # DPO pairwise sample data
data/dataset_info.json                   # LLaMA-Factory data manifest
personas/                                # persona markdown docs + template
schemas/sft_alpaca.schema.json           # SFT data contract
schemas/dpo_alpaca.schema.json           # DPO data contract
scripts/run-*.sh                         # training runners (run-smoke.sh, run-dpo-smoke.sh, ...)
scripts/check_no_set_x_with_secrets.py   # pre-commit helper (ADR-0010)
```

Reads freely, never modifies: everything else.

### B · Verifier (eval agent)

Owns:

```
configs/eval/                            # eval rubric + eval-specific configs
data/eval/                               # drift probes
scripts/eval/                            # eval pipeline modules
scripts/eval_persona.py                  # eval CLI entrypoint
outputs/eval/                            # per-run eval artifacts (gitignored)
```

Reads freely (contract dependencies): `personas/`, `schemas/`, `data/sft/`,
`data/dpo/`, trained adapter outputs under `saves/`.

Never modifies: anything under A's territory. If B needs a new `probe_type`
enum value or a new persona dimension, B **proposes** a change to A via the
user — A owns `schemas/` and `personas/`.

### C · Documenter (learning agent)

Owns:

```
docs/learning/                           # learning plan + theory backfill
```

Reads freely: all ADRs, all code, all docs.

Never modifies: anything outside `docs/learning/`. If C wants to link from
the top-level README to `docs/learning/README.md`, C asks A (README owner).

### D · Analyst (reserved, not yet active)

Will own when activated:

```
docs/experiments/                        # per-run retrospectives, hypothesis trees
```

Will read: `saves/`, `outputs/eval/`, training logs, eval reports.

Never will modify: A or B configs. Proposes hyperparameter / probe changes
to A and B via the user.

## Shared files — named owners

These files are necessarily touched by multiple agents. Each has **one
owner**; non-owners propose changes, owner merges.

| File | Owner | Non-owner protocol |
|---|---|---|
| `README.md` | A | append-only sections at bottom OK; structural changes via A |
| `Makefile` | A | new targets: propose inline in PR description, A wires them |
| `pyproject.toml` | A | new dependencies: tell A which group and why |
| `.gitignore` | A | new ignore patterns: propose via user |
| `.pre-commit-config.yaml` | A | new hooks: propose via user |
| `docs/adr/README.md` | ADR author + A | author adds their row at the bottom; A reviews |
| `docs/adr/NNNN-*.md` individual ADRs | the ADR's author | follow `~/.kiro/steering/adr-conventions.md` |
| `docs/runbooks/first-deploy.md` | A | append-only sections OK by non-A |
| `docs/collaboration.md` (this file) | A | changes go through user |

## ADR numbering (this project)

See `~/.kiro/steering/adr-conventions.md` for the general rules. Current max
ADR number: **check `docs/adr/README.md` before writing**. Claim a number by
committing a skeleton file first; then write the body.

## Handoff template

When finishing a work session and handing off to another agent via the user:

```
Role: A → B   (or similar)
Commits: <sha1>..<sha2>  (or "pushed through commit <sha>")
Done:
  - <one line per thing>
Left for next agent:
  - <one line per thing>
Gotchas (things the next agent cannot easily rediscover):
  - <e.g. "Qwen3 HF repo id is Qwen/Qwen3-8B not -Instruct, fixed in 4e7d0ff">
Specific ask:
  - <copy-paste-ready instruction for the next agent>
```
