"""Persona evaluation pipeline.

Modules:
  probes      — load drift-probe prompts and types
  candidates  — call a candidate model (OpenAI-compatible) to get replies
  judges      — LLM-as-judge clients (Claude / OpenAI) scoring replies against a rubric
  rubric      — rubric dimensions + judge prompt template
  report      — aggregate scores and render JSON + Markdown reports

CLI entry point: `scripts/eval_persona.py` (typer app).
"""

from __future__ import annotations

from . import candidates, judges, probes, report, rubric

__all__ = [
    "candidates",
    "judges",
    "probes",
    "report",
    "rubric",
]
