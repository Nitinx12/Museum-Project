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
    uv run scripts/python/dbt_runner.py --project-dir path/to/dbt_project

Requires `rich` (uv add rich if it isn't already a project dependency).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

LOG_DIR_NAME = "logs"
SILVER_SELECTOR = "tag:silver"
GOLD_SELECTOR = "tag:gold"


def find_project_root(start: Path) -> Path:
    """
    Walk upward from `start` looking for dbt_project.yml. Falls back to
    scanning every immediate subdirectory of the repo root (start's parent),
    since the dbt project commonly lives in its own folder (e.g. museum_dbt/)
    rather than at the repo root itself.
    """
    current = start.resolve()
    for parent in [current, *current.parents]:
        if (parent / "dbt_project.yml").exists():
            return parent

    repo_root = current.parent
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
        f"[bold red]Could not locate dbt_project.yml[/bold red] starting "
        f"from {start} or in any subfolder of {repo_root}. "
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


def run_stage(name: str, dbt_args: list[str], project_dir: Path, log_dir: Path) -> StageResult:
    command = ["uv", "run", "dbt", *dbt_args, "--project-dir", str(project_dir)]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{name}_{timestamp}.log"

    console.rule(f"[bold cyan]{name}[/bold cyan]")
    console.print(f"[dim]{' '.join(command)}[/dim]")

    start = time.monotonic()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    with open(log_path, "w", encoding="utf-8") as log_file:
        for line in process.stdout:  # type: ignore[union-attr]
            console.print(line, end="")
            log_file.write(line)
        process.wait()
    duration = time.monotonic() - start

    success = process.returncode == 0
    status = "[bold green]PASSED[/bold green]" if success else "[bold red]FAILED[/bold red]"
    console.print(f"{status} in {duration:.1f}s — log: {log_path}\n")

    return StageResult(name=name, command=" ".join(command), success=success,
                        duration_seconds=duration, log_path=log_path)


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
    console.print(f"[bold]logs:[/bold] {log_dir}\n")

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
        result = run_stage(name, dbt_args, project_dir, log_dir)
        results.append(result)
        if not result.success:
            console.print(f"[bold red]Stopping pipeline: {name} failed.[/bold red]")
            break

    print_summary(results)

    if any(not r.success for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
