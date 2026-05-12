#!/usr/bin/env python3
"""
check_no_set_x_with_secrets.py

Pre-commit hook enforcing ADR-0010 rule 1: scripts that read or export
secrets must not enable tracing (`set -x` / `set -o xtrace` / `set -euxo
pipefail`).

A script is flagged when BOTH are true:

1. It matches a shell file pattern (*.sh or a bash shebang)
2. It contains a line that exports / assigns a known secret name
   (HF_TOKEN, WANDB_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,
   AWS_SECRET_*, or fetches from SSM Parameter Store)
   AND another line enables tracing

Pass file paths as arguments (pre-commit invokes this way). Exits 0 when
clean, 1 when violations found, 2 on internal error.

Not a substitute for gitleaks (which catches checked-in literal secrets).
This hook catches the runtime-leak pattern that preceded the 2026-05-11
token incident: a `set -x` + `$(aws ssm get-parameter ...)` combination
that traced the resolved token to stdout.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Tracing activations. We err on the side of "any x in a set flags
# string" rather than trying to perfectly parse bash option syntax.
# The flag bundle after `-` is alphanumeric; we check that `x` appears
# anywhere in it (set -x, set -ex, set -euxo pipefail, etc.).
TRACE_PATTERNS = [
    re.compile(r"^\s*set\s+-[a-zA-Z]*x[a-zA-Z]*\b"),
    re.compile(r"^\s*set\s+-o\s+xtrace\b"),  # set -o xtrace
    re.compile(r"^\s*trap\s+.*\bxtrace\b"),  # paranoia: trap with xtrace
]

# Secret-handling signals. Any line matching one of these marks the file as
# "secret-touching".
SECRET_PATTERNS = [
    # Common env var names.
    re.compile(
        r"\b(HF_TOKEN|HUGGING_?FACE_?(HUB_)?TOKEN"
        r"|WANDB_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY"
        r"|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN"
        r"|GITHUB_TOKEN|GH_TOKEN"
        r"|DATABASE_URL|DB_PASSWORD)\b"
    ),
    # SSM / Secrets Manager fetches (whatever the local var name is).
    re.compile(r"\bssm\s+get-parameter\b.*--with-decryption"),
    re.compile(r"\bsecretsmanager\s+get-secret-value\b"),
]

SHEBANG_BASH_PATTERN = re.compile(rb"^#!.*\b(bash|sh)\b")


def is_shell_script(path: Path) -> bool:
    if path.suffix == ".sh":
        return True
    try:
        with path.open("rb") as f:
            first_line = f.readline(200)
    except OSError:
        return False
    return bool(SHEBANG_BASH_PATTERN.match(first_line))


def scan(path: Path) -> list[tuple[int, str]]:
    """Return a list of (line_no, line_text) flagged as violations."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []  # binary or unreadable — skip

    lines = text.splitlines()
    has_trace = False
    has_secret = False
    trace_line_numbers: list[int] = []
    secret_line_numbers: list[int] = []

    for i, line in enumerate(lines, start=1):
        # Skip comments (anywhere a `#` starts the stripped line).
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if any(p.search(line) for p in TRACE_PATTERNS):
            has_trace = True
            trace_line_numbers.append(i)
        if any(p.search(line) for p in SECRET_PATTERNS):
            has_secret = True
            secret_line_numbers.append(i)

    if not (has_trace and has_secret):
        return []

    # Build a readable violation record.
    violations: list[tuple[int, str]] = []
    for ln in trace_line_numbers:
        violations.append((ln, f"tracing enabled here: {lines[ln - 1].rstrip()}"))
    for ln in secret_line_numbers:
        violations.append((ln, f"secret accessed here: {lines[ln - 1].rstrip()}"))
    return violations


def main(argv: list[str]) -> int:
    rc = 0
    for raw_path in argv:
        path = Path(raw_path)
        if not path.is_file():
            continue
        if not is_shell_script(path):
            continue

        violations = scan(path)
        if not violations:
            continue

        rc = 1
        print(f"\n✗ {path}: tracing combined with secret handling (ADR-0010 rule 1)")
        for ln, msg in sorted(violations):
            print(f"    line {ln}: {msg}")
        print(
            "    Fix: remove `set -x` / `set -o xtrace` / the `x` in `set -euxo`,\n"
            "         or narrow tracing to blocks that never touch secrets.\n"
            "         See docs/adr/0010-secrets-never-baked-into-scripts.md"
        )

    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
