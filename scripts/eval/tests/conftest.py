"""pytest config for the eval test package.

Ensures the repo root is importable so `from scripts.eval...` works when
pytest is invoked from the repo root (which is how CI and local runs
invoke it).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
