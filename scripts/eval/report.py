"""Report aggregation and rendering.

Per-probe result → aggregate by (persona_id, language, probe_type) →
emit:
  results.jsonl       one line per probe (full verdict + reply text)
  summary.json        aggregates + run metadata (machine readable)
  summary.md          short markdown for humans / PR comments

A run_id is a UTC timestamp + short hash so parallel runs don't collide.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from .candidates import CandidateReply
from .judges import JudgeVerdict
from .probes import Probe
from .rubric import ALL_DIMENSIONS, PROBE_PRIMARY_DIMENSIONS, Dimension, Rubric


@dataclass(slots=True)
class ProbeResult:
    probe: Probe
    reply: CandidateReply
    verdict: JudgeVerdict
    hard_reject_hits: list[str]
    weighted_score: float

    def to_jsonable(self) -> dict:
        return {
            "probe_id": self.probe.probe_id,
            "probe_type": self.probe.probe_type,
            "persona_id": self.probe.persona_id,
            "language": self.probe.language,
            "instruction": self.probe.instruction,
            "history": [list(pair) for pair in self.probe.history],
            "reply": {
                "text": self.reply.text,
                "model": self.reply.model,
                "backend": self.reply.backend,
            },
            "verdict": {
                "scores": self.verdict.scores,
                "rationale": self.verdict.rationale,
                "judge_model": self.verdict.judge_model,
                "judge_backend": self.verdict.judge_backend,
                "parse_failed": self.verdict.parse_failed,
            },
            "hard_reject_hits": self.hard_reject_hits,
            "weighted_score": round(self.weighted_score, 4),
        }


def apply_hard_rejects(
    probe: Probe, reply_text: str, verdict: JudgeVerdict, rubric: Rubric
) -> list[str]:
    """Mutate verdict.scores in-place with hard-reject penalties. Return list of hits."""
    if not probe.hard_rejects:
        return []
    reply_lower = reply_text.lower()
    hits = [needle for needle in probe.hard_rejects if needle.lower() in reply_lower]
    if not hits:
        return []

    # Penalize the primary dimension(s) for this probe type.
    primary: tuple[Dimension, ...] = PROBE_PRIMARY_DIMENSIONS.get(probe.probe_type, ("voice",))
    penalty_per_dim = rubric.hard_reject_penalty
    for dim in primary:
        current = verdict.scores.get(dim, 3)
        verdict.scores[dim] = max(1, int(round(current - penalty_per_dim)))
    return hits


def build_result(
    probe: Probe, reply: CandidateReply, verdict: JudgeVerdict, rubric: Rubric
) -> ProbeResult:
    hits = apply_hard_rejects(probe, reply.text, verdict, rubric)
    weighted = rubric.weighted_score({d: float(v) for d, v in verdict.scores.items()})
    return ProbeResult(
        probe=probe, reply=reply, verdict=verdict, hard_reject_hits=hits, weighted_score=weighted
    )


def make_run_id() -> str:
    now = datetime.now(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    # Short random-ish suffix so concurrent runs don't collide
    suffix = hashlib.sha1(stamp.encode()).hexdigest()[:4]
    return f"{stamp}-{suffix}"


def _aggregate(results: list[ProbeResult]) -> dict:
    """Aggregate per-dimension means + slices by language / probe_type."""
    if not results:
        return {"count": 0}

    def _dim_means(items: list[ProbeResult]) -> dict[str, float]:
        return {
            d: round(mean(float(r.verdict.scores[d]) for r in items), 3) for d in ALL_DIMENSIONS
        }

    by_language_groups: dict[str, list[ProbeResult]] = {}
    for r in results:
        by_language_groups.setdefault(r.probe.language, []).append(r)
    by_language: dict[str, dict] = {
        lang: {
            "count": len(items),
            "weighted_mean": round(mean(x.weighted_score for x in items), 3),
            "dim_means": _dim_means(items),
        }
        for lang, items in by_language_groups.items()
    }

    by_probe_type_groups: dict[str, list[ProbeResult]] = {}
    for r in results:
        by_probe_type_groups.setdefault(r.probe.probe_type, []).append(r)
    by_probe_type: dict[str, dict] = {
        ptype: {
            "count": len(items),
            "weighted_mean": round(mean(x.weighted_score for x in items), 3),
            "dim_means": _dim_means(items),
        }
        for ptype, items in by_probe_type_groups.items()
    }

    return {
        "count": len(results),
        "weighted_mean": round(mean(r.weighted_score for r in results), 3),
        "dim_means": _dim_means(results),
        "hard_reject_rate": round(sum(1 for r in results if r.hard_reject_hits) / len(results), 3),
        "parse_failure_rate": round(
            sum(1 for r in results if r.verdict.parse_failed) / len(results), 3
        ),
        "by_language": by_language,
        "by_probe_type": by_probe_type,
    }


def write_reports(
    *,
    out_dir: Path,
    run_id: str,
    run_meta: dict,
    results: list[ProbeResult],
) -> tuple[Path, Path, Path]:
    """Write JSONL + summary.json + summary.md. Return the three paths."""
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = run_dir / "results.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r.to_jsonable(), ensure_ascii=False) + "\n")

    agg = _aggregate(results)
    summary = {"run_id": run_id, "run_meta": run_meta, "aggregates": agg}
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    md_path = run_dir / "summary.md"
    md_path.write_text(_render_markdown(run_id, run_meta, agg, results), encoding="utf-8")
    return jsonl_path, summary_path, md_path


def _render_markdown(run_id: str, meta: dict, agg: dict, results: list[ProbeResult]) -> str:
    lines: list[str] = []
    lines.append(f"# Eval run `{run_id}`")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    for key in (
        "candidate_backend",
        "candidate_model",
        "judge_backend",
        "judge_model",
        "probes_path",
        "persona_filter",
        "language_filter",
        "dry_run",
    ):
        if key in meta:
            lines.append(f"- **{key}**: `{meta[key]}`")
    lines.append("")

    if agg.get("count", 0) == 0:
        lines.append("_No probes were evaluated._")
        return "\n".join(lines) + "\n"

    lines.append("## Overall")
    lines.append("")
    lines.append(f"- **probes**: {agg['count']}")
    lines.append(f"- **weighted mean**: {agg['weighted_mean']:.2f}")
    lines.append(f"- **hard-reject rate**: {agg['hard_reject_rate']:.1%}")
    lines.append(f"- **judge parse-failure rate**: {agg['parse_failure_rate']:.1%}")
    lines.append("")
    lines.append("| Dimension | Mean |")
    lines.append("|---|---|")
    for d, m in agg["dim_means"].items():
        lines.append(f"| {d} | {m:.2f} |")
    lines.append("")

    if agg.get("by_language"):
        lines.append("## By language")
        lines.append("")
        lines.append(
            "| Lang | N | Weighted mean | voice | emotional_register | identity | boundaries |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for lang, s in sorted(agg["by_language"].items()):
            dm = s["dim_means"]
            lines.append(
                f"| {lang} | {s['count']} | {s['weighted_mean']:.2f} | "
                f"{dm['voice']:.2f} | {dm['emotional_register']:.2f} | "
                f"{dm['identity']:.2f} | {dm['boundaries']:.2f} |"
            )
        lines.append("")

    if agg.get("by_probe_type"):
        lines.append("## By probe type")
        lines.append("")
        lines.append(
            "| Type | N | Weighted mean | voice | emotional_register | identity | boundaries |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for ptype, s in sorted(agg["by_probe_type"].items()):
            dm = s["dim_means"]
            lines.append(
                f"| {ptype} | {s['count']} | {s['weighted_mean']:.2f} | "
                f"{dm['voice']:.2f} | {dm['emotional_register']:.2f} | "
                f"{dm['identity']:.2f} | {dm['boundaries']:.2f} |"
            )
        lines.append("")

    lines.append("## Low scorers (bottom 5 by weighted mean)")
    lines.append("")
    bottom = sorted(results, key=lambda r: r.weighted_score)[:5]
    for r in bottom:
        lines.append(f"### `{r.probe.probe_id}` — {r.probe.probe_type} / {r.probe.language}")
        lines.append(f"- **weighted**: {r.weighted_score:.2f}")
        lines.append(f"- **scores**: {dict(r.verdict.scores)}")
        if r.hard_reject_hits:
            lines.append(f"- **hard_reject_hits**: {r.hard_reject_hits}")
        lines.append(f"- **rationale**: {r.verdict.rationale or '_n/a_'}")
        lines.append("")
        lines.append(f"> user: {r.probe.instruction}")
        reply_preview = r.reply.text.replace("\n", " ")
        if len(reply_preview) > 240:
            reply_preview = reply_preview[:240] + "…"
        lines.append(f"> candidate: {reply_preview}")
        lines.append("")

    return "\n".join(lines) + "\n"


# Re-export for CLI convenience
__all__ = [
    "ProbeResult",
    "build_result",
    "make_run_id",
    "write_reports",
]
