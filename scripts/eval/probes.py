"""Drift probe loader.

A "probe" is one evaluation prompt tagged with:
- `probe_type`: which failure mode it exercises (identity, emotion-mirror, ...).
  The allowed set is the same enum used in schemas/dpo_alpaca.schema.json, so
  eval and DPO data use the same vocabulary.
- `persona_id` / `language`: which persona the probe targets. Eval loads the
  matching `personas/<persona_id>_<language>.md` to get the system prompt.
- `instruction` (+ optional `history`): what to send to the model.
- `hard_rejects` (optional): substrings that, if present in the reply, cost
  the model an automatic dimension penalty regardless of what the judge says.
  Used for deterministic guardrails like "As an AI language model".

Probe files are JSONL so they append cleanly. The seed file lives at
data/eval/probes_v1.jsonl and is committed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Keep this in sync with schemas/dpo_alpaca.schema.json `drift_probe` enum.
ProbeType = Literal[
    "identity",
    "emotion-mirror",
    "crisis",
    "code-switch",
    "boundary",
    "tone",
    "long-context",
    "other",
]


class Probe(BaseModel):
    """One evaluation prompt."""

    probe_id: str = Field(..., description="Stable short id, e.g. 'lily-id-01'.")
    probe_type: ProbeType
    persona_id: str
    language: str = Field(..., pattern=r"^[a-z]{2}$")
    instruction: str = Field(..., min_length=1)
    history: list[tuple[str, str]] = Field(default_factory=list)
    hard_rejects: list[str] = Field(
        default_factory=list,
        description="Case-insensitive substrings that, if present in the reply, "
        "trigger a deterministic penalty on the matching rubric dimension.",
    )
    notes: str = ""

    @field_validator("history", mode="before")
    @classmethod
    def _coerce_history(cls, v: object) -> object:
        # Accept list[list[str]] from JSON and coerce into tuples.
        if isinstance(v, list):
            return [tuple(pair) if isinstance(pair, list) else pair for pair in v]
        return v


def load_probes(
    path: Path, *, persona_id: str | None = None, language: str | None = None
) -> list[Probe]:
    """Load probes from a JSONL file, optionally filtered by persona/language."""
    if not path.exists():
        raise FileNotFoundError(f"probe file not found: {path}")

    probes: list[Probe] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{line_no} invalid JSON: {e.msg}") from e
            probes.append(Probe.model_validate(obj))

    if persona_id is not None:
        probes = [p for p in probes if p.persona_id == persona_id]
    if language is not None:
        probes = [p for p in probes if p.language == language]
    return probes


def load_system_prompt(personas_dir: Path, persona_id: str, language: str) -> str:
    """Extract the `## System prompt` code block from a persona markdown file.

    Convention: `personas/<persona_id>_<language>.md` has a section whose
    first fenced code block is the verbatim system prompt. We tolerate whitespace.
    """
    candidate = personas_dir / f"{persona_id}_{language}.md"
    if not candidate.exists():
        raise FileNotFoundError(
            f"persona file not found: {candidate}. Expected naming: <persona_id>_<language>.md"
        )

    text = candidate.read_text(encoding="utf-8")
    marker = "## System prompt"
    idx = text.find(marker)
    if idx < 0:
        raise ValueError(f"{candidate}: no '## System prompt' section found")

    tail = text[idx:]
    # First fenced block after the heading.
    fence_open = tail.find("```")
    if fence_open < 0:
        raise ValueError(f"{candidate}: system prompt fenced block not found")
    after_open = tail.find("\n", fence_open) + 1
    fence_close = tail.find("```", after_open)
    if fence_close < 0:
        raise ValueError(f"{candidate}: system prompt fence not closed")

    return tail[after_open:fence_close].strip()
