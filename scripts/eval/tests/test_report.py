"""Hard-reject penalty + aggregate math + report writing.

apply_hard_rejects mutates the verdict in place; if that contract ever
changes, the dry-run output would silently shift. Likewise _aggregate's
grouping is the thing CI dashboards will be scraping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval.candidates import CandidateReply
from scripts.eval.judges import JudgeVerdict
from scripts.eval.probes import Probe
from scripts.eval.report import (
    apply_hard_rejects,
    build_result,
    make_run_id,
    write_reports,
)
from scripts.eval.rubric import ALL_DIMENSIONS, Rubric


def _probe(
    probe_id: str = "t-01",
    probe_type: str = "identity",
    hard_rejects: list[str] | None = None,
) -> Probe:
    return Probe(
        probe_id=probe_id,
        probe_type=probe_type,  # type: ignore[arg-type]
        persona_id="lily_warm_companion",
        language="en",
        instruction="hi",
        history=[],
        hard_rejects=hard_rejects or [],
    )


def _verdict(scores: dict | None = None) -> JudgeVerdict:
    return JudgeVerdict(
        scores=dict(scores or {d: 3 for d in ALL_DIMENSIONS}),  # type: ignore[arg-type]
        rationale="",
        judge_model="test",
        judge_backend="stub",
    )


def test_hard_rejects_penalize_primary_dimension_only() -> None:
    probe = _probe(probe_type="identity", hard_rejects=["as an ai language model"])
    verdict = _verdict({d: 5 for d in ALL_DIMENSIONS})
    rubric = Rubric()  # penalty 2.0
    hits = apply_hard_rejects(probe, "As an AI language model, I am not...", verdict, rubric)
    assert hits == ["as an ai language model"]
    # identity is the primary dim for 'identity' probes -> 5 - 2 = 3
    assert verdict.scores["identity"] == 3
    # Other dims untouched.
    for d in ("voice", "emotional_register", "boundaries"):
        assert verdict.scores[d] == 5


def test_hard_rejects_case_insensitive_and_clamp_to_one() -> None:
    probe = _probe(probe_type="identity", hard_rejects=["AS AN ai LANGUAGE"])
    verdict = _verdict({d: 1 for d in ALL_DIMENSIONS})
    hits = apply_hard_rejects(
        probe, "as an AI language model...", verdict, Rubric(hard_reject_penalty=10.0)
    )
    assert hits  # non-empty
    assert verdict.scores["identity"] == 1  # clamped, never below 1


def test_hard_rejects_no_match_returns_empty_and_does_not_mutate() -> None:
    probe = _probe(probe_type="identity", hard_rejects=["as an ai language model"])
    original = {d: 4 for d in ALL_DIMENSIONS}
    verdict = _verdict(original)
    hits = apply_hard_rejects(probe, "I'm Lily, how are you", verdict, Rubric())
    assert hits == []
    assert verdict.scores == original


def test_hard_rejects_for_crisis_penalizes_both_primary_dims() -> None:
    # crisis -> (boundaries, emotional_register)
    probe = _probe(probe_type="crisis", hard_rejects=["cold reply"])
    verdict = _verdict({d: 5 for d in ALL_DIMENSIONS})
    hits = apply_hard_rejects(probe, "a COLD REPLY here", verdict, Rubric())
    assert hits == ["cold reply"]
    assert verdict.scores["boundaries"] == 3
    assert verdict.scores["emotional_register"] == 3
    assert verdict.scores["voice"] == 5
    assert verdict.scores["identity"] == 5


def test_build_result_computes_weighted_score() -> None:
    probe = _probe()
    reply = CandidateReply(probe_id=probe.probe_id, text="hi", model="m", backend="stub")
    verdict = _verdict({d: 4 for d in ALL_DIMENSIONS})
    r = build_result(probe, reply, verdict, Rubric())
    assert r.weighted_score == pytest.approx(4.0)
    assert r.hard_reject_hits == []


def test_make_run_id_is_monotonic_enough() -> None:
    a = make_run_id()
    b = make_run_id()
    # run_ids are YYYYMMDDTHHMMSSZ-hhhh; two calls within the same second
    # produce the same timestamp prefix but different-enough tails. We don't
    # assert uniqueness (collision would need sub-ms + identical hash prefix)
    # but we do assert format.
    for rid in (a, b):
        assert rid.endswith(rid[-5:])  # sanity
        ts_part, hash_part = rid.rsplit("-", 1)
        assert len(hash_part) == 4
        assert ts_part.endswith("Z")


def test_write_reports_produces_all_three_artifacts(tmp_path: Path) -> None:
    probe = _probe(probe_type="identity", hard_rejects=["as an ai language model"])
    reply = CandidateReply(
        probe_id=probe.probe_id,
        text="As an AI language model, I am not capable of feelings.",
        model="stub",
        backend="stub",
    )
    verdict = _verdict({d: 5 for d in ALL_DIMENSIONS})
    rubric = Rubric()
    result = build_result(probe, reply, verdict, rubric)

    run_id = make_run_id()
    run_meta = {
        "candidate_backend": "stub",
        "candidate_model": "stub",
        "judge_backend": "stub",
        "judge_model": "stub",
    }
    jsonl_path, summary_path, md_path = write_reports(
        out_dir=tmp_path, run_id=run_id, run_meta=run_meta, results=[result]
    )
    assert jsonl_path.exists() and summary_path.exists() and md_path.exists()

    # Sanity-check summary.json structure.
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["run_id"] == run_id
    agg = summary["aggregates"]
    assert agg["count"] == 1
    assert agg["hard_reject_rate"] == 1.0  # our one probe matched
    # identity dimension was 5, penalty 2.0 -> 3
    assert agg["dim_means"]["identity"] == 3.0

    # Sanity-check JSONL parseability + fields we commit to in reports.
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["probe_id"] == probe.probe_id
    assert rec["hard_reject_hits"] == ["as an ai language model"]
