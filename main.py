"""
main.py
========

Top-level entry point for the museum-etl pipeline. Mirrors the stage order
of the Airflow DAG (airflow/dags/museum_pipeline.py) and the PowerShell
runner (scripts/ps1/pipeline_runner.ps1) so the project can be driven locally
with a single command:

    uv run main.py                          # full pipeline (no tests)
    uv run main.py --full                   # full pipeline + full-refresh
    uv run main.py --skip-tests             # load + build only
    uv run main.py --bronze-only            # bronze_load + test_bronze
    uv run main.py --layers bronze silver   # run specific layers
    uv run main.py --dry-run                # show what would run, do nothing

Stage order (matches DAG and PS1 runner):
    1. bronze_load      -> scripts/python/incremental.py
    2. test_bronze      -> scripts/python/run_sql_tests.py --layer bronze
    3. build_silver_gold-> scripts/python/dbt_runner.py --skip-tests
    4. test_silver_gold -> scripts/python/run_sql_tests.py --layer silver --layer gold

Fail-fast: any non-zero exit code from a child script aborts the pipeline
and returns its exit code. Per-stage stdout is streamed live to the host
terminal AND persisted to logs/<stage>_<UTC-timestamp>.log, with a final
rich summary table covering every stage that ran (including ones that
failed and stopped the chain).

Environment setup is delegated to scripts/bash/setup_env.sh when it
exists, so secrets in .env are exported the same way the Docker image
expects them.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()

# This file lives at the project root, so the project root is the parent
# of __file__.
PROJECT_ROOT = Path(__file__).resolve().parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
PYTHON_DIR = SCRIPTS_DIR / "python"
BASH_DIR = SCRIPTS_DIR / "bash"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Stage model
# ---------------------------------------------------------------------------
@dataclass
class Stage:
    """One pipeline stage: a name, the uv command, and whether it can be
    skipped by a CLI flag (e.g. --skip-tests, --bronze-only)."""

    name: str
    uv_args: list[str]
    skip_with: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Bash setup hook
# ---------------------------------------------------------------------------
def source_bash_env() -> None:
    """If scripts/bash/setup_env.sh exists, source it in a bash subshell so
    .env variables (POSTGRES_*, MONGO_URI, etc.) are exported for the
    current process. Safe to call when the script is missing -- it's a
    convenience, not a hard requirement."""
    setup_script = BASH_DIR / "setup_env.sh"
    if not setup_script.is_file():
        return
    # `set -a` makes every subsequently assigned variable auto-exported,
    # so even a hand-written setup_env.sh that does `FOO=bar` without an
    # explicit `export` still propagates into this process.
    bash_cmd = f"source {setup_script} && env"
    try:
        result = subprocess.run(
            ["bash", "-c", bash_cmd],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        console.print(f"[yellow]⚠ Could not source {setup_script}: {exc}[/yellow]")
        return
    # Pull only the variables that were set by setup_env.sh -- never let it
    # overwrite unrelated host env vars (PATH, HOME, etc.).
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.startswith(("POSTGRES_", "MONGO_", "MUSEUM_", "AIRFLOW_", "DBT_")):
            os.environ[key] = value


# ---------------------------------------------------------------------------
# Stage execution
# ---------------------------------------------------------------------------
@dataclass
class StageResult:
    name: str
    command: str
    success: bool
    duration_seconds: float
    log_path: Path


def run_stage(stage: Stage) -> StageResult:
    """Run a single stage with `uv` and stream output live + persist to a
    timestamped log file. Returns the structured StageResult so the caller
    can decide whether to continue or stop."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"{stage.name}_{timestamp}.log"

    console.rule(f"[bold cyan]{stage.name}[/bold cyan]")
    console.print(f"[dim]$ uv {' '.join(stage.uv_args)}[/dim]")

    start = time.monotonic()
    # Popen + line-by-line read: gives the user real-time feedback instead
    # of waiting for the whole process to finish (subprocess.run(..., capture_output=True)
    # would buffer the entire output and only print it on completion).
    process = subprocess.Popen(
        ["uv", *stage.uv_args],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
            assert process.stdout is not None
            for line in process.stdout:
                console.print(line, end="")
                log_file.write(line)
        process.wait()
    except KeyboardInterrupt:
        # Forward Ctrl+C to the child so it gets a chance to clean up
        # (release Spark executors, close DB connections) before we exit.
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        raise
    duration = time.monotonic() - start

    success = process.returncode == 0
    status = "[bold green]PASSED[/bold green]" if success else "[bold red]FAILED[/bold red]"
    console.print(f"{status} in {duration:.1f}s — log: [dim]{log_path}[/dim]\n")

    return StageResult(
        name=stage.name,
        command="uv " + " ".join(stage.uv_args),
        success=success,
        duration_seconds=duration,
        log_path=log_path,
    )


# ---------------------------------------------------------------------------
# Stage construction
# ---------------------------------------------------------------------------
def build_stages(args: argparse.Namespace) -> list[Stage]:
    """Translate CLI flags into an ordered list of stages. The order here
    is the source of truth for the pipeline -- DAG and PS1 runner should
    stay in sync with it."""
    stages: list[Stage] = []

    # --- Bronze load (always runs) ---
    bronze_args = ["run", "scripts/python/incremental.py"]
    if args.full:
        bronze_args.append("--full-refresh")
    if args.dry_run:
        bronze_args.append("--dry-run")
    stages.append(Stage("bronze_load", bronze_args))

    # --- Bronze tests (skippable) ---
    if not args.skip_tests and "bronze" in args.layers:
        stages.append(Stage("test_bronze",
                            ["run", "scripts/python/run_sql_tests.py", "--layer", "bronze"]))

    # --- Silver/Gold build (skippable via --bronze-only) ---
    if "silver" in args.layers or "gold" in args.layers:
        if not args.bronze_only:
            build_args = ["run", "scripts/python/dbt_runner.py", "--skip-tests"]
            if args.full:
                build_args.append("--full-refresh")
            stages.append(Stage("build_silver_gold", build_args))

            # --- Silver/Gold tests ---
            if not args.skip_tests:
                stages.append(Stage("test_silver_gold", [
                    "run", "scripts/python/run_sql_tests.py",
                    "--layer", "silver", "--layer", "gold",
                ]))

    return stages


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------
def print_summary(results: list[StageResult], elapsed: float) -> None:
    table = Table(title="Pipeline summary", header_style="bold cyan")
    table.add_column("Stage", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Duration", justify="right")
    table.add_column("Log")

    for r in results:
        status = "[green]PASSED[/green]" if r.success else "[red]FAILED[/red]"
        table.add_row(r.name, status, f"{r.duration_seconds:.1f}s", str(r.log_path))

    console.print(table)
    overall = "PASSED" if all(r.success for r in results) else "FAILED"
    color = "green" if overall == "PASSED" else "red"
    console.print(f"\n[bold {color}]Pipeline {overall}[/bold {color}] in {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full museum-etl pipeline locally (same order as the Airflow DAG).",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip both test stages (test_bronze, test_silver_gold).",
    )
    parser.add_argument(
        "--bronze-only",
        action="store_true",
        help="Stop after bronze_load + test_bronze. Don't touch silver/gold.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Pass --full-refresh through to incremental.py and dbt_runner.py.",
    )
    parser.add_argument(
        "--layers",
        nargs="+",
        choices=["bronze", "silver", "gold"],
        default=["bronze", "silver", "gold"],
        help="Restrict which layers run (default: all three).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass --dry-run through to incremental.py (counts only, no writes).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    source_bash_env()

    console.print("[bold cyan]=== museum-etl pipeline ===[/bold cyan]")
    console.print(f"project root: {PROJECT_ROOT}")
    console.print(f"logs:         {LOG_DIR}")
    console.print(f"layers:       {', '.join(args.layers)}")
    if args.skip_tests:
        console.print("[yellow]tests:        SKIPPED (--skip-tests)[/yellow]")
    if args.bronze_only:
        console.print("[yellow]scope:        bronze-only (--bronze-only)[/yellow]")
    if args.full:
        console.print("[yellow]mode:         full-refresh (--full)[/yellow]")
    console.print("")

    stages = build_stages(args)
    if not stages:
        console.print("[bold red]No stages to run with the given flags.[/bold red]")
        return 2

    results: list[StageResult] = []
    overall_start = time.monotonic()
    for stage in stages:
        result = run_stage(stage)
        results.append(result)
        if not result.success:
            console.print(f"[bold red]Stopping pipeline: {stage.name} failed.[/bold red]")
            break
    overall_elapsed = time.monotonic() - overall_start

    print_summary(results, overall_elapsed)

    # 0 on success, 1 if any stage failed. Don't claim a "clean" run when
    # we only ran part of the chain because of an early failure.
    return 0 if all(r.success for r in results) else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Pipeline interrupted by user.[/bold yellow]")
        sys.exit(130)  # 128 + SIGINT (2) -- standard Unix convention
