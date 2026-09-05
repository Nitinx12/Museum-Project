#!/usr/bin/env python3
"""
scripts/python/dbt_runner.py

Orchestrates the dbt layer pipeline in order: silver run -> silver test ->
gold run -> gold test. Stops immediately if any stage fails, so a broken
silver layer never gets built on top of in the gold layer.

Assumes silver models carry `tags=['silver', ...]` the same way the gold
models here carry `tags=['gold', 'dimension']` / `tags=['gold', 'fact']`.
If your silver models use a different tag, change SILVER_SELECTOR below.

Usage (from anywhere in the repo):
    uv run scripts/python/dbt_runner.py
    uv run scripts/python/dbt_runner.py --skip-tests
    uv run scripts/python/dbt_runner.py --silver-only
    uv run scripts/python/dbt_runner.py --gold-only       # assumes silver already built
    uv run scripts/python/dbt_runner.py --full-refresh
    uv run scripts/python/dbt_runner.py --verbose         # full dbt debug output
    uv run scripts/python/dbt_runner.py --project-dir path/to/dbt_project

By default only model results, stats, and errors are printed. The full dbt
event stream is always written to logs/<stage>_<timestamp>.log.

Requires `rich` (uv add rich if it isn't already a project dependency).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TextIO

from rich.console import Console
from rich.table import Table

console = Console()

LOG_DIR_NAME = "logs"
SILVER_SELECTOR = "tag:silver"
GOLD_SELECTOR = "tag:gold"

# Event names that carry user-relevant information. Everything else
# (ConnectionUsed, SQLQuery, SendingEvent, telemetry, etc.) is debug noise
# we hide from stakeholder-facing output. Use --verbose to see everything.
STAKEHOLDER_EVENT_NAMES = frozenset([
    "LogModelResult",        # "4 of 5 OK created sql incremental model ..."
    "LogDatasetResult",      # seed / snapshot row counts
    "LogSeedResult",         # seed load output
    "LogTestResult",         # test pass/fail line
    "RunOperationResult",    # on-run-start/end output
    "FinishedRunningStats",  # "Finished running 5 incremental models in ..."
    "StatsLine",             # "Done. PASS=5 WARN=0 ERROR=0 ..."
    "EndOfRunSummary",       # "Completed successfully" / "Completed with errors"
    "CommandCompleted",      # "Command `cli run` succeeded after ..."
    "Note",                  # dbt's ad-hoc print() / warnings surfaced as Note
    "WarnError",             # warnings that need attention
    "PrintError",            # errors raised via print()
    "MessageEvent",          # generic message events
])


def _format_event(event) -> str | None:
    """Return a clean one-line string for stakeholder display, or None to skip.

    Filters out dbt's debug-level event flood (ConnectionUsed, SQLQuery,
    SendingEvent, telemetry, etc.) and keeps only the lines a stakeholder
    actually needs to see. Returns ANSI-coloured text via rich markup.
    """
    name = getattr(event, "name", "") or ""
    data = getattr(event, "data", None) or {}

    if name not in STAKEHOLDER_EVENT_NAMES:
        return None

    if name == "LogModelResult":
        node = data.get("node_info", {}) or {}
        status = data.get("status", "")
        return (
            f"[dim]{data.get('index', '?')}/{data.get('total', '?')}[/dim] "
            f"{node.get('node_name', '?')}: [bold]{status}[/bold] "
            f"[dim]({data.get('execution_time', 0):.1f}s)[/dim]"
        )

    if name == "FinishedRunningStats":
        return (
            f"[dim]Finished[/dim] "
            f"{data.get('stat_line', '')} "
            f"{data.get('execution', '')}"
        ).rstrip()

    if name == "StatsLine":
        stats = {s["key"]: s["value"] for s in data.get("stats", []) or []}
        return (
            f"PASS=[bold green]{stats.get('pass', 0)}[/bold green] "
            f"WARN=[bold yellow]{stats.get('warn', 0)}[/bold yellow] "
            f"ERROR=[bold red]{stats.get('error', 0)}[/bold red] "
            f"SKIP={stats.get('skip', 0)} "
            f"NO-OP={stats.get('noop', 0)} "
            f"REUSED={stats.get('reused', 0)} "
            f"TOTAL={stats.get('total', 0)}"
        )

    if name == "EndOfRunSummary":
        msg = data.get("msg") or "Completed"
        if "error" in msg.lower() or "fail" in msg.lower():
            return f"[bold red]{msg}[/bold red]"
        return f"[bold green]{msg}[/bold green]"

    if name == "CommandCompleted":
        elapsed = data.get("elapsed", 0)
        return f"[dim]Command completed in {elapsed:.1f}s[/dim]"

    if name == "Note":
        msg = data.get("msg") or ""
        return f"[yellow]![/yellow] {msg}" if msg else None

    if name == "WarnError":
        msg = data.get("msg") or ""
        return f"[bold yellow]WARN:[/bold yellow] {msg}" if msg else None

    if name == "PrintError":
        msg = data.get("msg") or ""
        return f"[bold red]ERROR:[/bold red] {msg}" if msg else None

    if name == "LogTestResult":
        msg = data.get("msg") or data.get("description") or ""
        return f"[dim]test:[/dim] {msg}" if msg else None

    if name in ("LogDatasetResult", "LogSeedResult"):
        msg = data.get("msg") or data.get("description") or ""
        return f"[dim]seed:[/dim] {msg}" if msg else None

    if name == "RunOperationResult":
        msg = data.get("msg") or ""
        return f"[dim]op:[/dim] {msg}" if msg else None

    if name == "MessageEvent":
        return data.get("msg") or None

    return None


def find_project_root(start: Path) -> Path:
    """
    Walk upward from `start` looking for dbt_project.yml. Falls back to
    scanning the immediate children of the repo root (the first ancestor
    whose children include a `scripts/` directory), since the dbt project
    commonly lives in its own folder (e.g. museum_dbt/) rather than at
    the repo root itself.
    """
    current = start.resolve()

    # Primary: walk upward looking for dbt_project.yml directly.
    for parent in [current, *current.parents]:
        if (parent / "dbt_project.yml").exists():
            return parent

    # Fallback: the dbt project may live in its own subfolder.
    # Find the repo root by walking upward until we find a `scripts/`
    # directory among the ancestor's children. This naturally stops
    # the search at the actual repo boundary (which has scripts/) and
    # also bounds it in test environments where pytest tmp dirs are shared.
    repo_root = None
    for ancestor in [current, *current.parents]:
        if (ancestor / "scripts").is_dir():
            repo_root = ancestor
            break
        # Hard stop at filesystem root so we never walk the entire filesystem.
        if ancestor == ancestor.parent:
            break

    if repo_root is None:
        console.print(
            f"[bold red]Could not locate dbt_project.yml[/bold red] starting "
            f"from {start}. No ancestor contains a scripts/ directory. "
            f"Pass --project-dir explicitly."
        )
        sys.exit(1)

    matches = sorted(
        child for child in repo_root.iterdir()
        if child.is_dir() and (child / "dbt_project.yml").exists()
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        console.print(
            f"[bold red]Found multiple dbt_project.yml candidates[/bold red] "
            f"under {repo_root}: {[str(m) for m in matches]}. "
            f"Pass --project-dir explicitly to disambiguate."
        )
        sys.exit(1)

    console.print(
        f"[bold red]Could not locate dbt_project.yml[/bold red] under {repo_root}. "
        f"Pass --project-dir explicitly."
    )
    sys.exit(1)


@dataclass
class StageResult:
    name: str
    command: str
    success: bool
    duration_seconds: float
    log_path: Path


def _dbt_log_lines(
    project_dir: Path,
    args: list[str],
    log_file: TextIO,
    verbose: bool = False,
) -> bool:
    """Invoke dbt via its Python API, streaming filtered output to stdout
    and the full event stream to a log file. Returns True on success.

    This replaces the previous subprocess path: under non-interactive bash
    on Windows, .venv/Scripts/dbt.exe is a uv trampoline that fails with
    'uv trampoline failed to canonicalize script path'. dbtRunner.invoke()
    avoids spawning a subprocess at all.

    In normal mode the stdout shows only stakeholder-relevant events
    (LogModelResult, StatsLine, etc.). The log file always gets every event
    in full for post-mortem debugging. Pass verbose=True to also dump every
    event to stdout.
    """
    from dbt.cli.main import dbtRunner

    invoke_args = [*args, "--project-dir", str(project_dir)]
    console.rule(f"[bold cyan]dbt {' '.join(args)}[/bold cyan]")
    log_file.write(f"dbt {' '.join(invoke_args)}\n")
    log_file.flush()

    def _stream_event(event) -> None:
        # Full event to log file always (unfiltered, for debugging).
        log_file.write(str(event) + "\n")
        log_file.flush()

        if verbose:
            console.print(str(event))
            return

        formatted = _format_event(event)
        if formatted is not None:
            console.print(formatted)

    runner = dbtRunner(callbacks=[_stream_event])
    start = time.monotonic()
    result = runner.invoke(invoke_args)
    duration = time.monotonic() - start

    if result.exception is not None:
        console.print(f"[red]{result.exception}[/red]")
        log_file.write(f"{result.exception}\n")

    status = "[bold green]PASSED[/bold green]" if result.success else "[bold red]FAILED[/bold red]"
    console.print(f"{status} in {duration:.1f}s")
    log_file.write(f"{'PASSED' if result.success else 'FAILED'} in {duration:.1f}s\n\n")
    log_file.flush()
    return bool(result.success)


def run_stage(
    name: str,
    dbt_args: list[str],
    project_dir: Path,
    log_dir: Path,
    verbose: bool = False,
) -> StageResult:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{name}_{timestamp}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.monotonic()
    with open(log_path, "w", encoding="utf-8") as log_file:
        success = _dbt_log_lines(project_dir, dbt_args, log_file, verbose=verbose)
    duration = time.monotonic() - start

    return StageResult(
        name=name,
        command=" ".join(dbt_args),
        success=success,
        duration_seconds=duration,
        log_path=log_path,
    )


def print_summary(results: list[StageResult]) -> None:
    table = Table(title="dbt pipeline summary")
    table.add_column("Stage")
    table.add_column("Status")
    table.add_column("Duration")
    table.add_column("Log")

    for r in results:
        status = "[bold green]PASSED[/bold green]" if r.success else "[bold red]FAILED[/bold red]"
        table.add_row(r.name, status, f"{r.duration_seconds:.1f}s", str(r.log_path))

    console.print(table)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the dbt silver -> gold pipeline.")
    parser.add_argument("--project-dir", type=Path, default=None,
                         help="Path to the dbt project (auto detected if omitted).")
    parser.add_argument("--skip-tests", action="store_true",
                         help="Run models only, skip both test stages.")
    parser.add_argument("--silver-only", action="store_true",
                         help="Stop after the silver layer.")
    parser.add_argument("--gold-only", action="store_true",
                         help="Skip silver, run gold only (assumes silver already built).")
    parser.add_argument("--full-refresh", action="store_true",
                         help="Pass --full-refresh through to every dbt run stage.")
    parser.add_argument("--verbose", action="store_true",
                         help="Stream every dbt event to stdout (full debug output). "
                              "Default shows only model results, stats, and errors.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.silver_only and args.gold_only:
        console.print("[bold red]--silver-only and --gold-only are mutually exclusive.[/bold red]")
        sys.exit(1)

    # This file lives at <project_root>/scripts/python/dbt_runner.py, so the
    # project root is three levels up. Logs land at <project_root>/logs.
    script_dir = Path(__file__).resolve().parent
    project_dir = args.project_dir or find_project_root(script_dir)
    log_dir = script_dir.parent.parent / LOG_DIR_NAME
    log_dir.mkdir(exist_ok=True)

    console.print(f"[bold]dbt project:[/bold] {project_dir}")
    console.print(f"[bold]logs:[/bold] {log_dir}")
    if args.verbose:
        console.print("[bold yellow]verbose:[/bold yellow] streaming every dbt event to stdout")
    console.print()

    run_extra = ["--full-refresh"] if args.full_refresh else []

    stages: list[tuple[str, list[str]]] = []

    if not args.gold_only:
        stages.append(("silver_run", ["run", "--select", SILVER_SELECTOR, *run_extra]))
        if not args.skip_tests:
            stages.append(("silver_test", ["test", "--select", SILVER_SELECTOR]))

    if not args.silver_only:
        stages.append(("gold_run", ["run", "--select", GOLD_SELECTOR, *run_extra]))
        if not args.skip_tests:
            stages.append(("gold_test", ["test", "--select", GOLD_SELECTOR]))

    results: list[StageResult] = []
    for name, dbt_args in stages:
        result = run_stage(name, dbt_args, project_dir, log_dir, verbose=args.verbose)
        results.append(result)
        if not result.success:
            console.print(f"[bold red]Stopping pipeline: {name} failed.[/bold red]")
            break

    print_summary(results)

    if any(not r.success for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
