"""Calibration aggregation math.

These tests don't touch any real judge — they hand-craft judges that return
canned verdicts, then check the aggregation matches what summary.json claims.
Covers the contract that CI dashboards and PR comments will scrape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.eval.calibrate import (
    CalibrationReport,
    DPORecord,
    calibrate,
    load_dpo_records,
    write_calibration_reports,
)
from scripts.eval.judges import JudgeVerdict
from scripts.eval.rubric import ALL_DIMENSIONS, Rubric


@dataclass
class _ScriptedJudge:
    """A judge that replays pre-programmed verdicts in order."""

    verdicts: list[JudgeVerdict]
    model: str = "scripted"
    backend: str = "scripted"
    _i: int = 0

    def score(self, **_: object) -> JudgeVerdict:
        v = self.verdicts[self._i]
        self._i += 1
        return v


def _verdict(scores: dict, parse_failed: bool = False) -> JudgeVerdict:
    return JudgeVerdict(
        scores=dict(scores),  # type: ignore[arg-type]
        rationale="",
        judge_model="scripted",
        judge_backend="scripted",
        parse_failed=parse_failed,
    )


def _record(drift_probe: str = "tone", language: str = "en", **overrides: object) -> DPORecord:
    base = {
        "instruction": "hi",
        "chosen": "warm reply",
        "rejected": "cold reply",
        "system": "You are a helpful persona (≥ 20 chars).",
        "history": [],
        "persona_id": "lily_warm_companion",
        "language": language,
        "drift_probe": drift_probe,
    }
    base.update(overrides)
    return DPORecord.model_validate(base)


def test_calibrate_pairs_length_matches_records() -> None:
    records = [_record(), _record(), _record()]
    verdicts = [
        _verdict({d: 4 for d in ALL_DIMENSIONS}),
        _verdict({d: 2 for d in ALL_DIMENSIONS}),
    ] * 3
    judge = _ScriptedJudge(verdicts=verdicts)
    pairs = calibrate(records=records, judge=judge, rubric=Rubric())
    assert len(pairs) == 3


def test_outcome_classification() -> None:
    records = [_record(), _record(), _record()]
    judge = _ScriptedJudge(
        verdicts=[
            _verdict({d: 5 for d in ALL_DIMENSIONS}),  # chosen #0
            _verdict({d: 3 for d in ALL_DIMENSIONS}),  # rejected #0
            _verdict({d: 3 for d in ALL_DIMENSIONS}),  # chosen #1
            _verdict({d: 3 for d in ALL_DIMENSIONS}),  # rejected #1
            _verdict({d: 2 for d in ALL_DIMENSIONS}),  # chosen #2
            _verdict({d: 4 for d in ALL_DIMENSIONS}),  # rejected #2
        ]
    )
    pairs = calibrate(records=records, judge=judge, rubric=Rubric())
    assert pairs[0].outcome == "agree"
    assert pairs[1].outcome == "tie"
    assert pairs[2].outcome == "disagree"
    assert pairs[0].margin == pytest.approx(2.0)
    assert pairs[2].margin == pytest.approx(-2.0)


def test_aggregate_rates_and_margin() -> None:
    records = [_record(language="en"), _record(language="en"), _record(language="zh")]
    judge = _ScriptedJudge(
        verdicts=[
            _verdict({d: 5 for d in ALL_DIMENSIONS}),  # chosen #0 -> agree
            _verdict({d: 3 for d in ALL_DIMENSIONS}),  # rejected #0
            _verdict({d: 4 for d in ALL_DIMENSIONS}),  # chosen #1 -> agree
            _verdict({d: 3 for d in ALL_DIMENSIONS}),  # rejected #1
            _verdict({d: 3 for d in ALL_DIMENSIONS}),  # chosen #2 -> tie
            _verdict({d: 3 for d in ALL_DIMENSIONS}),  # rejected #2
        ]
    )
    pairs = calibrate(records=records, judge=judge, rubric=Rubric())
    report = CalibrationReport(
        pairs=pairs,
        judge_model="scripted",
        judge_backend="scripted",
        rubric_version="v1",
    )
    agg = report.aggregate()
    assert agg["count"] == 3
    assert agg["agree_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert agg["tie_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert agg["disagree_rate"] == 0.0
    # margins: 2, 1, 0 -> mean = 1.0
    assert agg["mean_margin"] == pytest.approx(1.0)
    assert agg["by_language"]["en"]["agree_rate"] == 1.0
    assert agg["by_language"]["zh"]["tie_rate"] == 1.0


def test_per_dim_agree_rate_counts_ties_as_wins() -> None:
    # per-dim rate uses >=, matching the "chosen should not LOSE on any axis" framing.
    records = [_record()]
    judge = _ScriptedJudge(
        verdicts=[
            _verdict(
                {"voice": 4, "emotional_register": 3, "identity": 3, "boundaries": 3}
            ),  # chosen
            _verdict(
                {"voice": 3, "emotional_register": 3, "identity": 3, "boundaries": 5}
            ),  # rejected
        ]
    )
    pairs = calibrate(records=records, judge=judge, rubric=Rubric())
    report = CalibrationReport(
        pairs=pairs,
        judge_model="scripted",
        judge_backend="scripted",
        rubric_version="v1",
    )
    dim_rates = report.aggregate()["per_dim_agree_rate"]
    # chosen wins voice (4>3), ties emotional_register (3>=3), ties identity (3>=3), loses boundaries (3<5)
    assert dim_rates == {
        "voice": 1.0,
        "emotional_register": 1.0,
        "identity": 1.0,
        "boundaries": 0.0,
    }


def test_parse_failure_propagates_to_aggregate() -> None:
    records = [_record(), _record()]
    judge = _ScriptedJudge(
        verdicts=[
            _verdict({d: 3 for d in ALL_DIMENSIONS}, parse_failed=True),
            _verdict({d: 3 for d in ALL_DIMENSIONS}),
            _verdict({d: 3 for d in ALL_DIMENSIONS}),
            _verdict({d: 3 for d in ALL_DIMENSIONS}),
        ]
    )
    pairs = calibrate(records=records, judge=judge, rubric=Rubric())
    report = CalibrationReport(
        pairs=pairs, judge_model="scripted", judge_backend="scripted", rubric_version="v1"
    )
    assert report.aggregate()["parse_failure_rate"] == 0.5


def test_load_dpo_records_reads_multiple_files(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    a.write_text(
        json.dumps(
            [
                {
                    "instruction": "hi",
                    "chosen": "warm",
                    "rejected": "cold",
                    "system": "a persona system prompt long enough to pass validation",
                    "persona_id": "lily_warm_companion",
                    "language": "en",
                    "drift_probe": "tone",
                }
            ]
        ),
        encoding="utf-8",
    )
    b.write_text(
        json.dumps(
            [
                {
                    "instruction": "hi",
                    "chosen": "warm",
                    "rejected": "cold",
                    "system": "a persona system prompt long enough to pass validation",
                    "persona_id": "lily_warm_companion",
                    "language": "zh",
                    "drift_probe": "tone",
                }
            ]
        ),
        encoding="utf-8",
    )
    records = load_dpo_records([a, b])
    assert len(records) == 2
    assert {r.language for r in records} == {"en", "zh"}


def test_write_calibration_reports_produces_three_files(tmp_path: Path) -> None:
    records = [_record(), _record(language="zh", drift_probe="identity")]
    judge = _ScriptedJudge(
        verdicts=[
            _verdict({d: 4 for d in ALL_DIMENSIONS}),
            _verdict({d: 3 for d in ALL_DIMENSIONS}),
            _verdict({d: 5 for d in ALL_DIMENSIONS}),
            _verdict({d: 2 for d in ALL_DIMENSIONS}),
        ]
    )
    pairs = calibrate(records=records, judge=judge, rubric=Rubric())
    report = CalibrationReport(
        pairs=pairs,
        judge_model="scripted",
        judge_backend="scripted",
        rubric_version="v1",
        source_paths=["tests://fake"],
    )

    pairs_path, summary_path, md_path = write_calibration_reports(
        out_dir=tmp_path, run_id="test-run-01", report=report, rubric=Rubric()
    )
    assert pairs_path.exists()
    assert summary_path.exists()
    assert md_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_id"] == "test-run-01"
    assert summary["mode"] == "calibration"
    assert summary["aggregates"]["count"] == 2
    assert "by_language" in summary["aggregates"]
    assert "by_drift_probe" in summary["aggregates"]

    md = md_path.read_text(encoding="utf-8")
    assert "agree rate" in md
    assert "Per-dimension agree rate" in md
