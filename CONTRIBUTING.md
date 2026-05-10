# Contributing

## Dev setup

```bash
# Python env (Python 3.11 via uv)
make sync

# Activate
source .venv/bin/activate

# Install git hooks (skips if you already use a tool like amazon git-defender)
make pre-commit-install
```

From here on, every `git commit` runs ruff format, ruff check, cfn-lint, shellcheck,
and gitleaks automatically.

> **Note on `core.hooksPath`.** If your global git config sets
> `core.hooksPath` (e.g. Amazon's `git-defender`, or a corporate secret
> scanner), `pre-commit install` will refuse to install and `make
> pre-commit-install` prints an advisory instead of overriding it. That's
> deliberate — don't override company security tooling. Run
> `make pre-commit-run` manually before pushing; CI enforces the same
> checks on every PR.

## Common commands

```bash
make               # show all targets
make fmt           # format code (ruff)
make lint          # all linters (python + cloudformation + shell)
make typecheck     # pyright static types
make deploy        # create/update infra
make tunnel        # SSM port-forward to training instance
make destroy       # tear down infra
```

## Commit message convention

We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/).

Format:

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**

| Type | Use for |
|---|---|
| `feat` | New user-visible functionality |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `chore` | Maintenance — nothing affects src or docs |
| `refactor` | Code change that is neither fix nor feature |
| `build` | Dependency / build-system changes (pyproject.toml, Dockerfile) |
| `ci` | CI/CD configuration (.github/workflows, pre-commit) |
| `infra` | Infrastructure (CloudFormation / scripts for AWS) |
| `test` | Adding or fixing tests |
| `perf` | Performance improvement |

**Scope** is optional but helpful: `feat(sft): ...`, `fix(tunnel): ...`.

**Subject** uses the imperative mood: "add" not "added", lowercase, no trailing period.

**Body** explains *why*, not *what*. Wrap at 72 chars.

Examples:

```
feat(data): add multilingual SFT dataset schema

Define alpaca-style schema with explicit system field per record so
persona is stored inside the model weights during SFT, not only at
inference time via system prompt.

Refs: ADR-0005
```

```
fix(tunnel): use correct Sub escape for aws:InstanceId

CFN !Sub uses ${!var} to output a literal ${var}, not $${var}.
The old form caused cfn-lint E1021.
```

## Branching

- `main`: always deployable
- Feature branches: `feat/<short-name>`, `fix/<short-name>`
- Open PRs against `main`; keep them small (≤ 400 LOC diff where possible)

## Before you open a PR

```bash
make lint
make typecheck
make pre-commit-run
```

CI runs the same things and will block merges if anything fails.

## Architecture Decision Records

Significant choices (model selection, framework, infra pattern) go in
[`docs/adr/`](./docs/adr/). When proposing a change that alters an existing
ADR, supersede it rather than editing the original.

See [docs/adr/0000-adr-template.md](./docs/adr/0000-adr-template.md) for the
template and [docs/adr/README.md](./docs/adr/README.md) for the index.
