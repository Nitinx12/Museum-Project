#!/usr/bin/env python3
"""
scripts/run_sql_tests.py

Runs the project's own hand-written SQL tests -- not dbt tests. This is a
plain custom test suite: every .sql file under <project_root>/tests/ is a
test, dynamically discovered (drop a file in, it runs -- nothing to
register). Tests are grouped by layer, one subfolder per layer:

    tests/
      bronze/   check_no_null_ids.sql
                 check_row_counts_match_source.sql
      silver/    check_no_duplicate_keys.sql
      gold/      check_fact_totals_reconcile.sql
      ...        (any further subfolders are picked up the same way)

TEST CONVENTION -- "raise exception on failure"
------------------------------------------------
Each .sql file is plain SQL (typically a PL/pgSQL DO block) that only ever
raises an exception if the check fails; it does nothing on success. e.g.:

    DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM silver.tickets WHERE price < 0
        ) THEN
            RAISE EXCEPTION 'Found tickets with negative price';
        END IF;
    END $$;

This script executes each file inside its own transaction:
  - No exception raised  -> PASS  (transaction commits, a no-op either way)
  - Exception raised     -> FAIL  (transaction rolls back automatically;
                                    the RAISE EXCEPTION message is captured
                                    and reported)
  - Any other DB error (bad SQL, connection issue, etc.) -> ERROR, reported
    the same way as a FAIL so it can't be missed, but flagged separately.

Layers run in this order when present: bronze, silver, gold, then any other
subfolders alphabetically. Within a layer, test files run in alphabetical
order. All tests always run (a failure in one file doesn't skip the rest),
and every failure is collected -- then, once the whole suite has run, this
script raises a single aggregate SQLTestSuiteFailed listing everything that
failed, so nothing gets buried in the middle of the log.

USAGE
-----
    uv run scripts/run_sql_tests.py                  # every test, every layer
    uv run scripts/run_sql_tests.py --layer silver    # just tests/silver/
    uv run scripts/run_sql_tests.py --tests-dir path/to/tests

Exit code: 0 if every test passed, 1 if any test failed or errored,
2 for a setup problem (can't reach the tests dir or the database).
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

console = Console()

LOG_DIR_NAME = "logs"

# Preferred layer run order when these folders exist; anything else found
# under tests/ still runs, just after these, in alphabetical order.
PREFERRED_LAYER_ORDER = ["bronze", "silver", "gold"]

# ---------------------------------------------------------------------------
# Make `utils` importable regardless of the CWD this script is launched from.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.engine import postgres_engine  # noqa: E402


class SQLTestSuiteFailed(Exception):
    """Raised once, at the end of the run, if one or more individual tests
    failed or errored -- carries the full list so the caller (or Airflow)
    gets one clear summary instead of having to scrape the log."""


@dataclass
class TestResult:
    layer: str
    name: str
    path: Path
    status: str  # PASS | FAIL | ERROR
    seconds: float
    message: str = ""


def discover_layers(tests_dir: Path) -> list[Path]:
    """Every immediate subfolder of tests/ is a layer. Known layers run in
    PREFERRED_LAYER_ORDER; any others found are appended alphabetically."""
    all_layers = sorted(p for p in tests_dir.iterdir() if p.is_dir())
    known = [p for name in PREFERRED_LAYER_ORDER
             for p in all_layers if p.name == name]
    unknown = [p for p in all_layers if p.name not in PREFERRED_LAYER_ORDER]
    return known + unknown


def discover_tests(layer_dir: Path) -> list[Path]:
    return sorted(layer_dir.rglob("*.sql"))


def run_one_test(engine, layer: str, path: Path) -> TestResult:
    sql = path.read_text(encoding="utf-8")
    start = time.monotonic()
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
        return TestResult(layer=layer, name=path.stem, path=path, status="PASS",
                           seconds=time.monotonic() - start)
    except SQLAlchemyError as exc:
        # Prefer the database's own RAISE EXCEPTION message when present
        # (psycopg2 surfaces it as the driver error's primary message);
        # fall back to a cleaned-up one-liner otherwise.
        orig = getattr(exc, "orig", None)
        diag_message = getattr(getattr(orig, "diag", None), "message_primary", None)
        message = diag_message or (str(orig) if orig is not None else str(exc))
        message = " ".join(message.strip().splitlines())
        status = "FAIL" if diag_message else "ERROR"
        return TestResult(layer=layer, name=path.stem, path=path, status=status,
                           seconds=time.monotonic() - start, message=message)


def print_summary(results: list[TestResult], elapsed: float) -> None:
    table = Table(title="SQL Test Results", box=box.ROUNDED, header_style="bold cyan")
    table.add_column("Layer")
    table.add_column("Test")
    table.add_column("Status", justify="center")
    table.add_column("Time", justify="right")

    for r in results:
        color = {"PASS": "green", "FAIL": "red", "ERROR": "red"}[r.status]
        table.add_row(r.layer, r.name, f"[{color}]{r.status}[/{color}]", f"{r.seconds:.2f}s")
    console.print(table)

    failures = [r for r in results if r.status != "PASS"]
    if failures:
        fail_table = Table(title="Failures", box=box.MINIMAL, style="red")
        fail_table.add_column("Layer", no_wrap=True)
        fail_table.add_column("Test", no_wrap=True)
        fail_table.add_column("Message", overflow="fold", max_width=90)
        for r in failures:
            fail_table.add_row(r.layer, r.name, r.message or "(no message)")
        console.print(fail_table)

    n_passed = sum(1 for r in results if r.status == "PASS")
    has_issues = bool(failures)
    console.print(
        Panel(
            f"[bold {'red' if has_issues else 'green'}]"
            f"{n_passed}/{len(results)} passed in {elapsed:.2f}s -- "
            f"{'SQL TESTS FAILED' if has_issues else 'ALL SQL TESTS PASSED'}"
            f"[/bold {'red' if has_issues else 'green'}]",
            border_style="red" if has_issues else "green",
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the project's own SQL tests (tests/<layer>/*.sql).")
    parser.add_argument("--tests-dir", type=Path, default=None,
                         help="Path to the tests folder (default: <project_root>/tests).")
    parser.add_argument("--layer", type=str, default=None,
                         help="Only run tests in this one layer, e.g. --layer silver.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tests_dir = args.tests_dir or (PROJECT_ROOT / "tests")

    if not tests_dir.is_dir():
        console.print(f"[bold red]Tests folder not found:[/bold red] {tests_dir}")
        sys.exit(2)

    log_dir = PROJECT_ROOT / LOG_DIR_NAME
    log_dir.mkdir(exist_ok=True)

    layers = discover_layers(tests_dir)
    if args.layer:
        layers = [layer_dir for layer_dir in layers if layer_dir.name == args.layer]
        if not layers:
            console.print(f"[bold red]No layer folder named '{args.layer}' found under {tests_dir}[/bold red]")
            sys.exit(2)

    console.rule("[bold cyan]sql_tests[/bold cyan]")
    console.print(f"[bold]tests dir:[/bold] {tests_dir}")
    console.print(f"[bold]layers:[/bold] {', '.join(p.name for p in layers) or '(none found)'}\n")

    try:
        engine = postgres_engine()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]Could not connect to the database:[/bold red] {exc}")
        sys.exit(2)

    results: list[TestResult] = []
    start = time.time()
    try:
        for layer_dir in layers:
            test_files = discover_tests(layer_dir)
            if not test_files:
                continue
            console.print(f"[bold]{layer_dir.name}[/bold] ({len(test_files)} test file(s))")
            for path in test_files:
                result = run_one_test(engine, layer_dir.name, path)
                status_style = {"PASS": "green", "FAIL": "red", "ERROR": "red"}[result.status]
                console.print(f"  [{status_style}]{result.status}[/{status_style}]  {result.name} "
                              f"({result.seconds:.2f}s)" + (f" -- {result.message}" if result.message else ""))
                results.append(result)
    finally:
        engine.dispose()

    elapsed = time.time() - start

    # Also write a plain-text log for anything that isn't reading the Rich console output.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"sql_tests_{timestamp}.log"
    with open(log_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(f"{r.status}\t{r.layer}/{r.name}\t{r.seconds:.2f}s\t{r.message}\n")
    console.print(f"[dim]Log written to {log_path}[/dim]\n")

    print_summary(results, elapsed)

    failures = [r for r in results if r.status != "PASS"]
    if failures:
        summary = "; ".join(f"{r.layer}/{r.name}: {r.message or r.status}" for r in failures)
        try:
            raise SQLTestSuiteFailed(f"{len(failures)} SQL test(s) failed: {summary}")
        except SQLTestSuiteFailed:
            sys.exit(1)


if __name__ == "__main__":
    main()