#!/usr/bin/env python3
"""Persona evaluation CLI.

Evaluates a candidate model's persona fidelity using LLM-as-judge scoring +
deterministic drift-probe guardrails.

Examples:

  # Fully offline smoke (no API keys, no GPU) — exercises the full pipeline.
  uv run python scripts/eval_persona.py run \\
      --probes data/eval/probes_v1.jsonl \\
      --out    outputs/eval \\
      --candidate-backend stub \\
      --judge-backend     stub \\
      --dry-run

  # Real eval against a local vLLM server, judged by Claude.
  uv run python scripts/eval_persona.py run \\
      --probes data/eval/probes_v1.jsonl \\
      --candidate-backend openai \\
      --candidate-model   Qwen/Qwen3-8B \\
      --candidate-base-url http://localhost:8000/v1 \\
      --judge-backend     anthropic

  # List probes (filtering).
  uv run python scripts/eval_persona.py list \\
      --probes data/eval/probes_v1.jsonl --persona-id lily_warm_companion
"""
# ruff: noqa: B008
# B008 ("function call in default argument") fires on every `typer.Option(...)`
# default. That call shape IS typer's documented API for declaring CLI options;
# moving them to module-level constants hurts readability without any runtime
# benefit. Ignoring file-wide rather than per-line.

from __future__ import annotations

import sys
from pathlib import Path

# Make the repo root importable when this file is run directly
# (python scripts/eval_persona.py). `uv run python -m scripts.eval_persona`
# works without this, but we want both invocation styles to work.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import typer  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from scripts.eval.calibrate import (  # noqa: E402
    CalibrationReport,
    load_dpo_records,
    write_calibration_reports,
)
from scripts.eval.calibrate import (  # noqa: E402
    calibrate as run_calibration,
)
from scripts.eval.candidates import make_candidate_client  # noqa: E402
from scripts.eval.judges import make_judge  # noqa: E402
from scripts.eval.probes import (  # noqa: E402
    Probe,
    load_probes,
    load_system_prompt,
    validate_probes_file,
)
from scripts.eval.report import build_result, make_run_id, write_reports  # noqa: E402
from scripts.eval.rubric import load_rubric  # noqa: E402

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Persona evaluation pipeline (LLM-as-judge + drift probes).",
)
console = Console()


@app.command("run")
def run(
    probes: Path = typer.Option(..., help="Path to probes JSONL file."),
    out: Path = typer.Option(Path("outputs/eval"), help="Directory for run artifacts."),
    personas_dir: Path = typer.Option(
        Path("personas"), help="Directory containing persona markdown files."
    ),
    rubric_config: Path | None = typer.Option(
        None, "--rubric", help="Optional rubric YAML (weights, penalties)."
    ),
    persona_id: str | None = typer.Option(None, help="Filter probes by persona_id."),
    language: str | None = typer.Option(None, help="Filter probes by ISO 639-1 language code."),
    limit: int | None = typer.Option(None, min=1, help="Cap number of probes (smoke)."),
    # Candidate
    candidate_backend: str = typer.Option("stub", help="Candidate backend: stub | openai."),
    candidate_model: str = typer.Option(
        "stub-default", help="Candidate model id (ignored by stub)."
    ),
    candidate_base_url: str | None = typer.Option(
        None, help="OpenAI-compatible base URL (e.g., http://localhost:8000/v1 for vLLM)."
    ),
    candidate_api_key: str | None = typer.Option(
        None, help="Candidate API key (defaults to OPENAI_API_KEY env)."
    ),
    # Judge
    judge_backend: str = typer.Option("stub", help="Judge backend: stub | anthropic | openai."),
    judge_model: str | None = typer.Option(None, help="Judge model override."),
    judge_api_key: str | None = typer.Option(
        None, help="Judge API key (defaults to env: ANTHROPIC_API_KEY / OPENAI_API_KEY)."
    ),
    judge_base_url: str | None = typer.Option(None, help="Judge base URL (OpenAI backend only)."),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Force both backends to 'stub' (overrides --candidate-backend / --judge-backend).",
    ),
) -> None:
    """Run evaluation over a probe set and write reports."""
    # Load .env for local dev convenience.
    load_dotenv(override=False)

    if dry_run:
        candidate_backend = "stub"
        judge_backend = "stub"
        console.print("[yellow]--dry-run active: forcing stub backends[/yellow]")

    all_probes: list[Probe] = load_probes(probes, persona_id=persona_id, language=language)
    if limit is not None:
        all_probes = all_probes[:limit]
    if not all_probes:
        console.print("[red]No probes matched the given filters.[/red]")
        raise typer.Exit(code=2)

    rubric = load_rubric(rubric_config)
    candidate_client = make_candidate_client(
        backend=candidate_backend,
        model=candidate_model,
        base_url=candidate_base_url,
        api_key=candidate_api_key,
    )
    judge_client = make_judge(
        backend=judge_backend,
        model=judge_model,
        api_key=judge_api_key,
        base_url=judge_base_url,
    )

    # Cache persona system prompts by (persona_id, language) so we don't re-read
    # the markdown per probe.
    system_cache: dict[tuple[str, str], str] = {}

    def system_for(p: Probe) -> str:
        key = (p.persona_id, p.language)
        if key not in system_cache:
            system_cache[key] = load_system_prompt(personas_dir, p.persona_id, p.language)
        return system_cache[key]

    results = []
    console.print(
        f"[bold]Evaluating[/bold] {len(all_probes)} probe(s) "
        f"candidate=[cyan]{candidate_backend}:{candidate_client.model}[/cyan] "
        f"judge=[cyan]{judge_backend}:{judge_client.model}[/cyan]"
    )
    for probe in all_probes:
        system_prompt = system_for(probe)
        reply = candidate_client.generate(system=system_prompt, probe=probe)
        verdict = judge_client.score(
            persona_system=system_prompt,
            instruction=probe.instruction,
            history=probe.history,
            candidate_reply=reply.text,
        )
        result = build_result(probe, reply, verdict, rubric)
        results.append(result)
        console.print(
            f"  [dim]{probe.probe_id}[/dim] "
            f"[{probe.probe_type}/{probe.language}] "
            f"weighted=[bold]{result.weighted_score:.2f}[/bold] "
            f"scores={dict(verdict.scores)}"
            + (f" hard_rejects={result.hard_reject_hits}" if result.hard_reject_hits else "")
        )

    run_id = make_run_id()
    run_meta = {
        "candidate_backend": candidate_backend,
        "candidate_model": candidate_client.model,
        "judge_backend": judge_backend,
        "judge_model": judge_client.model,
        "probes_path": str(probes),
        "persona_filter": persona_id or "",
        "language_filter": language or "",
        "dry_run": dry_run,
        "rubric_version": rubric.version,
    }
    jsonl_path, summary_path, md_path = write_reports(
        out_dir=out, run_id=run_id, run_meta=run_meta, results=results
    )

    console.print()
    console.print(f"[green]✓ run {run_id}[/green]")
    console.print(f"  results : {jsonl_path}")
    console.print(f"  summary : {summary_path}")
    console.print(f"  report  : {md_path}")


@app.command("list")
def list_probes(
    probes: Path = typer.Option(..., help="Path to probes JSONL file."),
    persona_id: str | None = typer.Option(None),
    language: str | None = typer.Option(None),
) -> None:
    """List probes (with optional filters)."""
    items = load_probes(probes, persona_id=persona_id, language=language)
    table = Table(title=f"{len(items)} probe(s)")
    table.add_column("probe_id")
    table.add_column("type")
    table.add_column("persona")
    table.add_column("lang")
    table.add_column("instruction", overflow="fold")
    for p in items:
        preview = p.instruction if len(p.instruction) <= 80 else p.instruction[:77] + "…"
        table.add_row(p.probe_id, p.probe_type, p.persona_id, p.language, preview)
    console.print(table)


@app.command("calibrate")
def calibrate(
    dpo: list[Path] = typer.Option(
        ...,
        "--dpo",
        help="Path(s) to DPO JSON file(s) (data/dpo/*.json). Repeat for multiple.",
    ),
    out: Path = typer.Option(Path("outputs/eval/calibration"), help="Directory for run artifacts."),
    rubric_config: Path | None = typer.Option(
        None, "--rubric", help="Optional rubric YAML (weights, penalties)."
    ),
    judge_backend: str = typer.Option("stub", help="Judge backend: stub | anthropic | openai."),
    judge_model: str | None = typer.Option(None, help="Judge model override."),
    judge_api_key: str | None = typer.Option(None, help="Judge API key (defaults to env)."),
    judge_base_url: str | None = typer.Option(None, help="Judge base URL (OpenAI backend only)."),
    language: str | None = typer.Option(None, help="Filter DPO records by ISO 639-1 language."),
    drift_probe: str | None = typer.Option(None, help="Filter DPO records by drift_probe value."),
    limit: int | None = typer.Option(None, min=1, help="Cap number of DPO records (smoke)."),
) -> None:
    """Calibrate the judge against committed DPO preference pairs.

    For each (chosen, rejected) pair, the judge scores both replies. We report
    how often the judge's weighted score for `chosen` exceeds `rejected` —
    agreement rate, mean margin, and slices by language / drift_probe.

    A healthy judge should show ≥ 90% agreement on our committed DPO data
    (which is human-curated, so disagreements point at judge / rubric gaps).
    """
    load_dotenv(override=False)

    records = load_dpo_records(dpo)
    if language is not None:
        records = [r for r in records if r.language == language]
    if drift_probe is not None:
        records = [r for r in records if r.drift_probe == drift_probe]
    if limit is not None:
        records = records[:limit]
    if not records:
        console.print("[red]No DPO records matched the given filters.[/red]")
        raise typer.Exit(code=2)

    rubric = load_rubric(rubric_config)
    judge = make_judge(
        backend=judge_backend,
        model=judge_model,
        api_key=judge_api_key,
        base_url=judge_base_url,
    )

    console.print(
        f"[bold]Calibrating[/bold] {len(records)} pair(s) "
        f"judge=[cyan]{judge_backend}:{judge.model}[/cyan] "
        f"rubric=[cyan]{rubric.version}[/cyan]"
    )
    pairs = run_calibration(records=records, judge=judge, rubric=rubric)
    for p in pairs:
        marker = {
            "agree": "[green]✓[/green]",
            "tie": "[yellow]~[/yellow]",
            "disagree": "[red]✗[/red]",
        }[p.outcome]
        console.print(
            f"  {marker} #{p.index} {p.drift_probe}/{p.language} "
            f"chosen={p.weighted_chosen:.2f} rejected={p.weighted_rejected:.2f} "
            f"margin={p.margin:+.2f}"
        )

    report = CalibrationReport(
        pairs=pairs,
        judge_model=judge.model,
        judge_backend=judge_backend,
        rubric_version=rubric.version,
        source_paths=[str(p) for p in dpo],
    )
    run_id = make_run_id()
    pairs_path, summary_path, md_path = write_calibration_reports(
        out_dir=out, run_id=run_id, report=report, rubric=rubric
    )
    agg = report.aggregate()
    console.print()
    console.print(f"[green]✓ calibration {run_id}[/green]")
    console.print(
        f"  agree={agg['agree_rate']:.1%}  tie={agg['tie_rate']:.1%}  "
        f"disagree={agg['disagree_rate']:.1%}  mean_margin={agg['mean_margin']:+.2f}"
    )
    console.print(f"  pairs   : {pairs_path}")
    console.print(f"  summary : {summary_path}")
    console.print(f"  report  : {md_path}")


@app.command("validate")
def validate(
    probes: Path = typer.Option(..., help="Path to probes JSONL file."),
    schema: Path | None = typer.Option(
        None, help="Override the default data/eval/probe.schema.json path."
    ),
) -> None:
    """Validate a probes JSONL file against data/eval/probe.schema.json.

    Exit code 0 on success, 1 if any line violates the schema. Belt-and-
    suspenders on top of the pydantic loader — useful in pre-commit / CI.
    """
    errors = validate_probes_file(probes, schema_path=schema)
    if not errors:
        console.print(f"[green]✓[/green] {probes} — all records valid")
        return
    console.print(f"[red]✗[/red] {probes} — {len(errors)} error(s):")
    for line_no, msg in errors:
        console.print(f"  line {line_no}: {msg}")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
