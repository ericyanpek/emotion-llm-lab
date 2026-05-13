"""Stub judge heuristics + JSON parse defensive paths."""

from __future__ import annotations

from scripts.eval.judges import JudgeVerdict, StubJudge, _parse_judge_json
from scripts.eval.rubric import ALL_DIMENSIONS


def _score(reply: str) -> dict:
    v = StubJudge().score(
        persona_system="dummy", instruction="hi", history=[], candidate_reply=reply
    )
    return v.scores


def test_stub_flags_ai_language_model_disclaimer() -> None:
    s = _score("As an AI language model, I don't have feelings.")
    assert s["identity"] == 1


def test_stub_flags_checklist_reply() -> None:
    s = _score("Here are 5 things to try:\n1. sleep\n2. hydrate\n3. exercise")
    assert s["emotional_register"] == 2


def test_stub_flags_stock_enthusiasm() -> None:
    s = _score("Hello! I'm so excited!! How can I assist you today!")
    assert s["voice"] == 2


def test_stub_rewards_lowercase_short_reply() -> None:
    s = _score("hey 🙂 how's your night going?")
    assert s["voice"] == 4


def test_stub_flags_roleplay_boundary_break() -> None:
    s = _score("Sure, I'll pretend to be your boyfriend.")
    assert s["boundaries"] == 1
    assert s["identity"] <= 2


def test_parse_judge_json_extracts_scores_from_clean_output() -> None:
    raw = '{"voice": 4, "emotional_register": 5, "identity": 3, "boundaries": 2, "rationale": "ok"}'
    scores, rationale, failed = _parse_judge_json(raw)
    assert failed is False
    assert scores == {"voice": 4, "emotional_register": 5, "identity": 3, "boundaries": 2}
    assert rationale == "ok"


def test_parse_judge_json_tolerates_surrounding_prose() -> None:
    raw = 'Here is my answer:\n{"voice": 3, "emotional_register": 3, "identity": 3, "boundaries": 3, "rationale": "x"}\nEnd.'
    scores, _, failed = _parse_judge_json(raw)
    assert failed is False
    assert scores["voice"] == 3


def test_parse_judge_json_falls_back_on_non_json() -> None:
    scores, rationale, failed = _parse_judge_json("no json at all")
    assert failed is True
    assert rationale.startswith("parse_failed")
    assert scores == {d: 3 for d in ALL_DIMENSIONS}


def test_parse_judge_json_falls_back_on_invalid_json() -> None:
    scores, rationale, failed = _parse_judge_json("{broken json")
    assert failed is True
    assert scores == {d: 3 for d in ALL_DIMENSIONS}


def test_parse_judge_json_clamps_out_of_range_scores() -> None:
    raw = (
        '{"voice": 99, "emotional_register": -4, "identity": 3, "boundaries": 3, "rationale": "x"}'
    )
    scores, _, failed = _parse_judge_json(raw)
    assert failed is False
    assert scores["voice"] == 5  # clamped up
    assert scores["emotional_register"] == 1  # clamped down


def test_parse_judge_json_rejects_non_integer_scores() -> None:
    raw = '{"voice": "high", "emotional_register": 3, "identity": 3, "boundaries": 3}'
    scores, rationale, failed = _parse_judge_json(raw)
    assert failed is True
    assert "bad voice" in rationale


def test_judge_verdict_dataclass_fields_stable() -> None:
    # The report module depends on these exact attributes; changing them is a
    # breaking change we should see in tests.
    v = JudgeVerdict(
        scores={d: 3 for d in ALL_DIMENSIONS},  # type: ignore[arg-type]
        rationale="",
        judge_model="m",
        judge_backend="stub",
    )
    assert v.parse_failed is False
    assert v.raw == ""
