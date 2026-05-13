"""Judge calibration harness.

Before we trust the judge's scores as a signal about a training run, we
should know: does the judge reliably prefer `chosen` over `rejected` on
our DPO pairs?

For each DPO record, we ask the judge to score both `chosen` and `rejected`
against the shared persona system prompt. Aggregates:

  agree_rate          share of pairs where weighted(chosen) >  weighted(rejected)
  tie_rate            share of pairs where weighted(chosen) == weighted(rejected)
  disagree_rate       share of pairs where weighted(chosen) <  weighted(rejected)
  mean_margin         mean of (chosen - rejected) across pairs (higher = judge agrees more strongly)
  margin_std          standard deviation of margins
  per_dim_agree_rate  per-dimension agree rate (chosen >= rejected on that dim)

Sliceable by `language` and by `drift_probe`. A low agree rate on a given
slice means either:
  - the judge isn't sensitive to that failure mode (fix: rubric / judge prompt), or
  - the DPO data mislabels that probe type (fix: curate the pair)

Both are valuable signals.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from pydantic import BaseModel, Field

from .judges import JudgeClient, JudgeVerdict
from .rubric import ALL_DIMENSIONS, Rubric


class DPORecord(BaseModel):
    """Minimal view over a DPO record — only what calibration needs."""

    instruction: str
    chosen: str
    rejected: str
    system: str = Field(..., min_length=1)
    history: list[list[str]] = Field(default_factory=list)
    persona_id: str = ""
    language: str = "en"
    drift_probe: str = "other"


@dataclass(slots=True)
class PairCalibration:
    """One (chosen, rejected) pair judged against the persona."""

    index: int
    persona_id: str
    language: str
    drift_probe: str
    instruction: str
    chosen_verdict: JudgeVerdict
    rejected_verdict: JudgeVerdict
    weighted_chosen: float
    weighted_rejected: float

    @property
    def margin(self) -> float:
        return self.weighted_chosen - self.weighted_rejected

    @property
    def outcome(self) -> str:
        if self.margin > 1e-9:
            return "agree"
        if self.margin < -1e-9:
            return "disagree"
        return "tie"

    def to_jsonable(self) -> dict:
        return {
            "index": self.index,
            "persona_id": self.persona_id,
            "language": self.language,
            "drift_probe": self.drift_probe,
            "instruction": self.instruction,
            "chosen": {
                "scores": self.chosen_verdict.scores,
                "rationale": self.chosen_verdict.rationale,
                "parse_failed": self.chosen_verdict.parse_failed,
            },
            "rejected": {
                "scores": self.rejected_verdict.scores,
                "rationale": self.rejected_verdict.rationale,
                "parse_failed": self.rejected_verdict.parse_failed,
            },
            "weighted_chosen": round(self.weighted_chosen, 4),
            "weighted_rejected": round(self.weighted_rejected, 4),
            "margin": round(self.margin, 4),
            "outcome": self.outcome,
        }


@dataclass(slots=True)
class CalibrationReport:
    pairs: list[PairCalibration]
    judge_model: str
    judge_backend: str
    rubric_version: str
    source_paths: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.pairs)

    def aggregate(self) -> dict[str, Any]:
        if not self.pairs:
            return {"count": 0}

        outcomes = [p.outcome for p in self.pairs]
        margins = [p.margin for p in self.pairs]

        overall: dict[str, Any] = {
            "count": len(self.pairs),
            "agree_rate": round(outcomes.count("agree") / len(outcomes), 4),
            "tie_rate": round(outcomes.count("tie") / len(outcomes), 4),
            "disagree_rate": round(outcomes.count("disagree") / len(outcomes), 4),
            "mean_margin": round(mean(margins), 4),
            "margin_std": round(pstdev(margins), 4) if len(margins) > 1 else 0.0,
            "per_dim_agree_rate": _per_dim_agree_rate(self.pairs),
            "parse_failure_rate": round(
                sum(
                    1
                    for p in self.pairs
                    if p.chosen_verdict.parse_failed or p.rejected_verdict.parse_failed
                )
                / len(self.pairs),
                4,
            ),
        }

        by_language: dict[str, dict[str, Any]] = {}
        by_probe: dict[str, dict[str, Any]] = {}
        lang_groups: dict[str, list[PairCalibration]] = {}
        probe_groups: dict[str, list[PairCalibration]] = {}
        for p in self.pairs:
            lang_groups.setdefault(p.language, []).append(p)
            probe_groups.setdefault(p.drift_probe, []).append(p)
        for lang, items in lang_groups.items():
            by_language[lang] = _slice_summary(items)
        for probe, items in probe_groups.items():
            by_probe[probe] = _slice_summary(items)
        overall["by_language"] = by_language
        overall["by_drift_probe"] = by_probe
        return overall


def _slice_summary(items: list[PairCalibration]) -> dict[str, Any]:
    outcomes = [p.outcome for p in items]
    margins = [p.margin for p in items]
    return {
        "count": len(items),
        "agree_rate": round(outcomes.count("agree") / len(outcomes), 4),
        "tie_rate": round(outcomes.count("tie") / len(outcomes), 4),
        "disagree_rate": round(outcomes.count("disagree") / len(outcomes), 4),
        "mean_margin": round(mean(margins), 4),
    }


def _per_dim_agree_rate(pairs: list[PairCalibration]) -> dict[str, float]:
    """Fraction of pairs where chosen's score ≥ rejected's score, per dimension."""
    out: dict[str, float] = {}
    for d in ALL_DIMENSIONS:
        wins = sum(
            1
            for p in pairs
            if p.chosen_verdict.scores.get(d, 0) >= p.rejected_verdict.scores.get(d, 0)
        )
        out[d] = round(wins / len(pairs), 4)
    return out


def load_dpo_records(paths: list[Path]) -> list[DPORecord]:
    """Load DPO records from one or more Alpaca-style JSON files."""
    records: list[DPORecord] = []
    for path in paths:
        if not path.exists():
            raise FileNotFoundError(f"DPO file not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError(f"{path}: expected a JSON array of records")
        for obj in raw:
            records.append(DPORecord.model_validate(obj))
    return records


def calibrate(
    *,
    records: list[DPORecord],
    judge: JudgeClient,
    rubric: Rubric,
) -> list[PairCalibration]:
    """Score each (chosen, rejected) pair via the judge. Returns one PairCalibration per record."""
    pairs: list[PairCalibration] = []
    for i, rec in enumerate(records):
        history: list[tuple[str, str]] = [(pair[0], pair[1]) for pair in rec.history]
        chosen_v = judge.score(
            persona_system=rec.system,
            instruction=rec.instruction,
            history=history,
            candidate_reply=rec.chosen,
        )
        rejected_v = judge.score(
            persona_system=rec.system,
            instruction=rec.instruction,
            history=history,
            candidate_reply=rec.rejected,
        )
        weighted_chosen = rubric.weighted_score(
            {d: float(chosen_v.scores[d]) for d in ALL_DIMENSIONS}
        )
        weighted_rejected = rubric.weighted_score(
            {d: float(rejected_v.scores[d]) for d in ALL_DIMENSIONS}
        )
        pairs.append(
            PairCalibration(
                index=i,
                persona_id=rec.persona_id,
                language=rec.language,
                drift_probe=rec.drift_probe,
                instruction=rec.instruction,
                chosen_verdict=chosen_v,
                rejected_verdict=rejected_v,
                weighted_chosen=weighted_chosen,
                weighted_rejected=weighted_rejected,
            )
        )
    return pairs


def write_calibration_reports(
    *,
    out_dir: Path,
    run_id: str,
    report: CalibrationReport,
    rubric: Rubric,
) -> tuple[Path, Path, Path]:
    """Write pairs.jsonl + summary.json + summary.md. Returns the three paths."""
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    pairs_path = run_dir / "pairs.jsonl"
    with pairs_path.open("w", encoding="utf-8") as f:
        for p in report.pairs:
            f.write(json.dumps(p.to_jsonable(), ensure_ascii=False) + "\n")

    agg = report.aggregate()
    summary = {
        "run_id": run_id,
        "mode": "calibration",
        "judge": {"backend": report.judge_backend, "model": report.judge_model},
        "rubric": {
            "version": rubric.version,
            "weights": rubric.weights,
            "hard_reject_penalty": rubric.hard_reject_penalty,
        },
        "sources": report.source_paths,
        "aggregates": agg,
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = run_dir / "summary.md"
    md_path.write_text(_render_markdown(run_id, summary, report), encoding="utf-8")
    return pairs_path, summary_path, md_path


def _render_markdown(run_id: str, summary: dict, report: CalibrationReport) -> str:
    agg = summary["aggregates"]
    lines: list[str] = []
    lines.append(f"# Judge calibration `{run_id}`")
    lines.append("")
    lines.append(f"- **judge**: `{summary['judge']['backend']}:{summary['judge']['model']}`")
    lines.append(f"- **rubric**: {summary['rubric']['version']}")
    lines.append(f"- **sources**: {', '.join(summary['sources']) or '_none_'}")
    lines.append("")

    if agg.get("count", 0) == 0:
        lines.append("_No pairs calibrated._")
        return "\n".join(lines) + "\n"

    # Target thresholds are advisory — surfaced here to make success legible.
    agree = agg["agree_rate"]
    verdict = "🟢 good" if agree >= 0.90 else ("🟡 marginal" if agree >= 0.75 else "🔴 unreliable")
    lines.append("## Overall")
    lines.append("")
    lines.append(f"- **pairs**: {agg['count']}")
    lines.append(f"- **agree rate**: {agree:.1%} ({verdict}; target ≥ 90%)")
    lines.append(f"- **tie rate**: {agg['tie_rate']:.1%}")
    lines.append(f"- **disagree rate**: {agg['disagree_rate']:.1%}")
    lines.append(f"- **mean margin**: {agg['mean_margin']:.2f}  **std**: {agg['margin_std']:.2f}")
    lines.append(f"- **judge parse-failure rate**: {agg['parse_failure_rate']:.1%}")
    lines.append("")

    lines.append("## Per-dimension agree rate (chosen ≥ rejected)")
    lines.append("")
    lines.append("| Dimension | Rate |")
    lines.append("|---|---|")
    for d, r in agg["per_dim_agree_rate"].items():
        lines.append(f"| {d} | {r:.1%} |")
    lines.append("")

    if agg.get("by_language"):
        lines.append("## By language")
        lines.append("")
        lines.append("| Lang | N | Agree | Tie | Disagree | Mean margin |")
        lines.append("|---|---|---|---|---|---|")
        for lang, s in sorted(agg["by_language"].items()):
            lines.append(
                f"| {lang} | {s['count']} | {s['agree_rate']:.1%} | {s['tie_rate']:.1%} | "
                f"{s['disagree_rate']:.1%} | {s['mean_margin']:+.2f} |"
            )
        lines.append("")

    if agg.get("by_drift_probe"):
        lines.append("## By drift_probe")
        lines.append("")
        lines.append("| Probe | N | Agree | Tie | Disagree | Mean margin |")
        lines.append("|---|---|---|---|---|---|")
        for probe, s in sorted(agg["by_drift_probe"].items()):
            lines.append(
                f"| {probe} | {s['count']} | {s['agree_rate']:.1%} | {s['tie_rate']:.1%} | "
                f"{s['disagree_rate']:.1%} | {s['mean_margin']:+.2f} |"
            )
        lines.append("")

    # Surface disagreements prominently — each one is a calibration lead.
    disagreements = [p for p in report.pairs if p.outcome == "disagree"]
    if disagreements:
        lines.append("## Disagreements (judge preferred `rejected` ≥ `chosen`)")
        lines.append("")
        lines.append(f"_{len(disagreements)} pair(s)_")
        for p in disagreements:
            lines.append(
                f"- **#{p.index}** `{p.drift_probe}` / `{p.language}` — margin `{p.margin:+.2f}`"
            )
            lines.append(f"  - user: {p.instruction}")
            lines.append(f"  - chosen scores: `{dict(p.chosen_verdict.scores)}`")
            lines.append(f"  - rejected scores: `{dict(p.rejected_verdict.scores)}`")
        lines.append("")

    return "\n".join(lines) + "\n"


__all__ = [
    "DPORecord",
    "PairCalibration",
    "CalibrationReport",
    "load_dpo_records",
    "calibrate",
    "write_calibration_reports",
]
