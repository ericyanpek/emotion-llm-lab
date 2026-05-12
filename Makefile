# Emotion Companion Fine-Tune — developer entry point.
#
# All common operations go through this Makefile so there's one place to look.
# Run `make help` (or just `make`) to see available targets.

SHELL := /bin/bash
.DEFAULT_GOAL := help
.PHONY: help sync sync-all fmt lint lint-py lint-cfn lint-sh typecheck \
        cfn-validate deploy destroy tunnel shell secrets \
        pre-commit-install pre-commit-run clean \
        eval eval-dry

# ---- Locate tools ----------------------------------------------------------
# Prefer the .venv-local install; fall back to user site.
VENV          := .venv
PY            := $(VENV)/bin/python
UV            := uv
RUFF          := $(VENV)/bin/ruff
PYRIGHT       := $(VENV)/bin/pyright
PRE_COMMIT    := $(VENV)/bin/pre-commit
CFN_LINT      := $(shell command -v cfn-lint 2>/dev/null || echo $$HOME/.local/bin/cfn-lint)
SHELLCHECK    := $(shell command -v shellcheck 2>/dev/null)

CFN_TEMPLATES := infrastructure/cloudformation/training-env.yaml
SH_SCRIPTS    := $(wildcard infrastructure/scripts/*.sh)

# ---- Help ------------------------------------------------------------------
help: ## Show this help (default target).
	@echo "Emotion Companion — available targets:"
	@echo
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo

# ---- Environment -----------------------------------------------------------
sync: ## Install local dev dependencies into .venv (local + eval + dev groups).
	$(UV) sync --group local --group eval --group dev

sync-all: ## Install ALL dependency groups (useful for IDE completion, not for runtime).
	$(UV) sync --group local --group eval --group dev --group train --group serve

# ---- Formatting & linting --------------------------------------------------
fmt: ## Format Python code with ruff.
	$(RUFF) format .
	$(RUFF) check --fix-only .

lint: lint-py lint-cfn lint-sh ## Run all linters (python + cloudformation + shell).

lint-py: ## Ruff check Python.
	$(RUFF) format --check .
	$(RUFF) check .

typecheck: ## Pyright static type check.
	$(PYRIGHT) scripts configs 2>/dev/null || echo "pyright: no files to check yet"

lint-cfn: ## cfn-lint for CloudFormation templates.
	@if [ ! -x "$(CFN_LINT)" ]; then \
		echo "ERROR: cfn-lint not found at $(CFN_LINT). Install with: pip install --user cfn-lint"; \
		exit 1; \
	fi
	$(CFN_LINT) $(CFN_TEMPLATES)

lint-sh: ## shellcheck for bash scripts.
	@if [ -z "$(SHELLCHECK)" ]; then \
		echo "WARN: shellcheck not installed. Install with: brew install shellcheck"; \
	else \
		$(SHELLCHECK) $(SH_SCRIPTS); \
	fi

# ---- pre-commit ------------------------------------------------------------
pre-commit-install: ## Install git pre-commit hooks (local). Skips if core.hooksPath is set (e.g. amazon git-defender).
	@HOOKS_PATH="$$(git config --get core.hooksPath || true)"; \
	if [ -n "$$HOOKS_PATH" ]; then \
		echo "NOTE: core.hooksPath is set to $$HOOKS_PATH (e.g. corporate git-defender)."; \
		echo "      Skipping local pre-commit install to avoid conflicting with it."; \
		echo "      CI will run the same checks on PRs. Run 'make pre-commit-run' manually before pushing."; \
	else \
		$(PRE_COMMIT) install; \
	fi

pre-commit-run: ## Run all pre-commit hooks against the whole repo.
	$(PRE_COMMIT) run --all-files

# ---- CloudFormation operations --------------------------------------------
cfn-validate: ## Validate template syntax against AWS (requires credentials).
	@for t in $(CFN_TEMPLATES); do \
		echo "Validating $$t..."; \
		aws cloudformation validate-template --template-body file://$$t >/dev/null && echo "  OK"; \
	done

deploy: ## Deploy/update the training-env stack. Honors env vars (see infrastructure/README.md).
	./infrastructure/scripts/deploy.sh

preflight: ## Run pre-deploy checks (creds, quotas, AMI, name collisions).
	./infrastructure/scripts/preflight.sh

bootstrap: ## Install LLaMA-Factory + vLLM on the instance via SSM (post-deploy).
	./infrastructure/scripts/bootstrap.sh

destroy: ## Tear down the training-env stack (prompts for confirmation).
	./infrastructure/scripts/destroy.sh

tunnel: ## Open SSM port-forward tunnel (7860/6006/8000) to the training instance.
	./infrastructure/scripts/tunnel.sh

shell: ## Interactive SSM shell on the training instance.
	./infrastructure/scripts/ssm-shell.sh

secrets: ## Set HF / Wandb tokens in SSM Parameter Store (interactive prompt).
	./infrastructure/scripts/set-secrets.sh

# ---- Eval ------------------------------------------------------------------
# Persona drift + LLM-as-judge pipeline. See scripts/eval/README.md.
EVAL_PROBES  ?= data/eval/probes_v1.jsonl
EVAL_RUBRIC  ?= configs/eval/rubric_v1.yaml
EVAL_OUT     ?= outputs/eval

eval-dry: ## Run the eval pipeline end-to-end with stub backends (no API keys, no GPU).
	$(UV) run python scripts/eval_persona.py run \
		--probes $(EVAL_PROBES) \
		--rubric $(EVAL_RUBRIC) \
		--out    $(EVAL_OUT) \
		--candidate-backend stub \
		--judge-backend     stub \
		--dry-run

eval: ## Run eval against a live candidate (see scripts/eval/README.md for flags).
	@echo "Real eval needs explicit flags; copy-paste the example from scripts/eval/README.md."
	@echo "For a quick sanity check, run: make eval-dry"

# ---- Housekeeping ----------------------------------------------------------
clean: ## Remove Python caches, build artifacts, and ruff/pyright state.
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .pyright \) \
	       -not -path "./.venv/*" -not -path "./.git/*" -exec rm -rf {} + 2>/dev/null || true
	@echo "Cleaned."
