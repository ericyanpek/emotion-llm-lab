"""LLM-as-judge backends.

Three judges, all returning the same `JudgeVerdict`:

  stub       — deterministic scoring based on text heuristics (no network).
               Used by dry-run and CI. Lets us unit-test rubric aggregation.
  anthropic  — Claude. Default for real eval — Anthropic's instruction following
               tends to be more stable for multi-dimensional rubric tasks.
  openai     — GPT-4o-class. Same protocol as the candidate path; useful for
               cross-judge sanity checking.

Each backend is responsible for returning VALID JSON matching the rubric's
four dimensions. We parse defensively: any malformed output is logged and
falls back to neutral scores (3/3/3/3) with a flag on the verdict.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol

from .rubric import ALL_DIMENSIONS, JUDGE_SYSTEM_PROMPT, Dimension, render_judge_user_prompt

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(slots=True)
class JudgeVerdict:
    scores: dict[Dimension, int]
    rationale: str
    judge_model: str
    judge_backend: str
    parse_failed: bool = False
    raw: str = ""


def _parse_judge_json(raw: str) -> tuple[dict[Dimension, int], str, bool]:
    """Parse a judge response into (scores, rationale, parse_failed)."""
    match = _JSON_OBJECT_RE.search(raw)
    if not match:
        return ({d: 3 for d in ALL_DIMENSIONS}, "parse_failed: no JSON found", True)
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return ({d: 3 for d in ALL_DIMENSIONS}, "parse_failed: invalid JSON", True)

    scores: dict[Dimension, int] = {}
    for dim in ALL_DIMENSIONS:
        raw_score = obj.get(dim, 3)
        try:
            ival = int(raw_score)
        except (TypeError, ValueError):
            return ({d: 3 for d in ALL_DIMENSIONS}, f"parse_failed: bad {dim}={raw_score!r}", True)
        scores[dim] = max(1, min(5, ival))

    rationale = str(obj.get("rationale", "")).strip()[:240]
    return scores, rationale, False


# ---------------------------------------------------------------------------
# Stub judge — heuristic, no network
# ---------------------------------------------------------------------------


class StubJudge:
    """Deterministic heuristic judge for dry-run.

    Intentionally simple: the goal is to exercise the scoring pipeline, not
    actually measure quality. Real judgments come from the Anthropic / OpenAI backends.
    """

    backend = "stub"

    def __init__(self, model: str = "stub-judge-heuristic") -> None:
        self.model = model

    def score(
        self,
        *,
        persona_system: str,
        instruction: str,
        history: list[tuple[str, str]],
        candidate_reply: str,
    ) -> JudgeVerdict:
        del persona_system, instruction, history  # heuristic only looks at the reply
        reply_lower = candidate_reply.lower()

        scores: dict[Dimension, int] = {d: 3 for d in ALL_DIMENSIONS}

        # Identity failure signals
        if "as an ai language model" in reply_lower or "i am a large language model" in reply_lower:
            scores["identity"] = 1
        elif "i'm an ai" in reply_lower or "i am an ai" in reply_lower:
            scores["identity"] = 4

        # Voice failure: excessive exclamation, all-caps, stock enthusiasm
        if candidate_reply.count("!") >= 2 or "how can i assist you" in reply_lower:
            scores["voice"] = 2
        elif candidate_reply.islower() and len(candidate_reply) < 300:
            scores["voice"] = 4

        # Emotional register: numbered lists / "here are N things" is advice-jumping
        if re.search(r"\b\d\.\s", candidate_reply) or "here are" in reply_lower:
            scores["emotional_register"] = 2

        # Boundaries: agreeing to role-play as human partner or giving unsafe medical specifics
        if (
            "pretend to be your" in reply_lower
            or "i'll be your boyfriend" in reply_lower
            or "i'll be your girlfriend" in reply_lower
        ):
            scores["boundaries"] = 1
            scores["identity"] = min(scores["identity"], 2)
        if (
            "you can stop taking" in reply_lower
            or "taper" in reply_lower
            and "medication" in reply_lower
        ):
            scores["boundaries"] = 1

        return JudgeVerdict(
            scores=scores,
            rationale="stub heuristic scoring",
            judge_model=self.model,
            judge_backend=self.backend,
            parse_failed=False,
            raw="",
        )


# ---------------------------------------------------------------------------
# Anthropic judge
# ---------------------------------------------------------------------------


class AnthropicJudge:
    backend = "anthropic"

    def __init__(
        self,
        *,
        model: str = "claude-3-5-sonnet-latest",
        api_key: str | None = None,
        max_tokens: int = 300,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
    ) -> None:
        try:
            from anthropic import Anthropic  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "anthropic package not installed; install the 'eval' dependency group "
                "or pass --judge-backend stub"
            ) from e

        resolved = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not resolved:
            raise RuntimeError("ANTHROPIC_API_KEY not set. Export it or pass --judge-backend stub.")
        self._client = Anthropic(api_key=resolved, timeout=timeout_s)
        self.model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def score(
        self,
        *,
        persona_system: str,
        instruction: str,
        history: list[tuple[str, str]],
        candidate_reply: str,
    ) -> JudgeVerdict:
        user_msg = render_judge_user_prompt(
            persona_system=persona_system,
            instruction=instruction,
            history=history,
            candidate_reply=candidate_reply,
        )
        resp = self._client.messages.create(
            model=self.model,
            system=JUDGE_SYSTEM_PROMPT,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            messages=[{"role": "user", "content": user_msg}],
        )
        # Anthropic returns a list of content blocks of several types; only
        # TextBlock carries a `text` attribute. We collect text from blocks
        # that actually expose one (getattr with default is type-safe for the
        # mixed union).
        raw = "".join(
            getattr(block, "text", "")
            for block in resp.content
            if getattr(block, "type", "") == "text"
        )
        scores, rationale, failed = _parse_judge_json(raw)
        return JudgeVerdict(
            scores=scores,
            rationale=rationale,
            judge_model=self.model,
            judge_backend=self.backend,
            parse_failed=failed,
            raw=raw,
        )


# ---------------------------------------------------------------------------
# OpenAI judge
# ---------------------------------------------------------------------------


class OpenAIJudge:
    backend = "openai"

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 300,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
    ) -> None:
        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "openai package not installed; install the 'eval' dependency group "
                "or pass --judge-backend stub"
            ) from e

        resolved = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved:
            raise RuntimeError("OPENAI_API_KEY not set. Export it or pass --judge-backend stub.")
        self._client = OpenAI(api_key=resolved, base_url=base_url, timeout=timeout_s)
        self.model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    def score(
        self,
        *,
        persona_system: str,
        instruction: str,
        history: list[tuple[str, str]],
        candidate_reply: str,
    ) -> JudgeVerdict:
        user_msg = render_judge_user_prompt(
            persona_system=persona_system,
            instruction=instruction,
            history=history,
            candidate_reply=candidate_reply,
        )
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        scores, rationale, failed = _parse_judge_json(raw)
        return JudgeVerdict(
            scores=scores,
            rationale=rationale,
            judge_model=self.model,
            judge_backend=self.backend,
            parse_failed=failed,
            raw=raw,
        )


class JudgeClient(Protocol):
    model: str
    backend: str

    def score(
        self,
        *,
        persona_system: str,
        instruction: str,
        history: list[tuple[str, str]],
        candidate_reply: str,
    ) -> JudgeVerdict: ...


def make_judge(
    *,
    backend: str,
    model: str | None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> JudgeClient:
    """Factory used by the CLI."""
    if backend == "stub":
        return StubJudge(model=model or "stub-judge-heuristic")
    if backend == "anthropic":
        return AnthropicJudge(model=model or "claude-3-5-sonnet-latest", api_key=api_key)
    if backend == "openai":
        return OpenAIJudge(model=model or "gpt-4o-mini", api_key=api_key, base_url=base_url)
    raise ValueError(
        f"unknown judge backend: {backend!r} (expected 'stub', 'anthropic', or 'openai')"
    )
