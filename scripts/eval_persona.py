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

from scripts.eval.candidates import make_candidate_client  # noqa: E402
from scripts.eval.judges import make_judge  # noqa: E402
from scripts.eval.probes import Probe, load_probes, load_system_prompt  # noqa: E402
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


if __name__ == "__main__":
    app()
