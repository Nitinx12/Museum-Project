"""
transform.py

Silver-layer transformation pipeline.

Step order (ORDER MATTERS — snapshots feed silver models):
  1. dbt snapshot          <- SCD Type 2 history rebuilt first
  2. dbt run   silver      <- silver models built from snapshots + sources
  3. dbt test  silver      <- 106 tests; 2 documented WARNs are acceptable

Known acceptable warnings (documented source-data gaps, not pipeline bugs):
  - assert_product_size               — 2 records with no matching product size at source
                                        (tests/silver/assert_product_size.sql)
  - not_null_canvas_size_height_inches — 7 canvas size records missing height at source
                                        (models/silver/schema.yml)

Pass-rate gate:
  Pipeline is marked SUCCESS only when:
    (passed + warned) / total  >=  PASS_THRESHOLD   (default 0.95 / 95%)

  Current baseline (last clean run):
    PASS=104  WARN=2  ERROR=0  SKIP=0  TOTAL=106  ->  pass_rate=100.0%  PASSED

  Override at runtime:
    DBT_PASS_THRESHOLD=0.90 python -m scripts.Transformation.transform

  On failure the pipeline:
    1. Logs a CRITICAL data-quality alert with the breakdown
    2. Writes a JSON failure report to <project_root>/watermark/transform/dq_failure_<timestamp>.json
    3. Exits with code 1 to fail any upstream orchestrator (Airflow, etc.)

Usage:
    python -m scripts.Transformation.transform
    python -m scripts.Transformation.transform --full-refresh
"""

from __future__ import annotations

import json
import os
import re
import sys
import subprocess
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# -- sys.path fix --------------------------------------------------------------
def _find_scripts_root() -> Path | None:
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "utils" / "engine.py").exists():
            return current
        if (current / "scripts" / "utils" / "engine.py").exists():
            return current / "scripts"
        current = current.parent
    return None


def _find_project_root() -> Path | None:
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "pyproject.toml").exists() or (current / "main.py").exists():
            return current
        current = current.parent
    return None


_scripts_root = _find_scripts_root()
if _scripts_root is None:
    # Fallback for Airflow Docker environment
    _scripts_root = Path("/opt/airflow/project/scripts")

if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))

_project_root = _find_project_root()
if _project_root is None:
    env_root = os.getenv("PROJECT_ROOT")
    _project_root = Path(env_root) if env_root else Path("/opt/airflow/project")


# -- Project imports -----------------------------------------------------------
try:
    from utils.engine import postgres_engine
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        f"Cannot import utils.engine. Scripts root: {_scripts_root}"
    ) from e

try:
    from utils.logger import get_logger
except ModuleNotFoundError as e:
    raise ModuleNotFoundError(
        "Cannot find utils/logger.py under utils/."
    ) from e


# -- Config --------------------------------------------------------------------
DBT_PROJECT_DIR  = Path(os.getenv("DBT_PROJECT_DIR",  str(_project_root / "museum_dbt")))
DBT_PROFILES_DIR = Path(os.getenv("DBT_PROFILES_DIR", str(Path.home() / ".dbt")))
DBT_TARGET       = os.getenv("DBT_TARGET",  "dev")
DBT_THREADS      = os.getenv("DBT_THREADS", "4")
ISO_FMT          = "%Y-%m-%dT%H:%M:%S"


# -- Data-quality pass-rate threshold ------------------------------------------
# PASS + WARN both count as passing (WARNs are documented source-data gaps).
# Raise/lower per environment via the env var:
#   DEV / CI  -> DBT_PASS_THRESHOLD=0.85
#   STAGING   -> DBT_PASS_THRESHOLD=0.90
#   PROD      -> DBT_PASS_THRESHOLD=0.95  (default)
_raw_threshold = os.getenv("DBT_PASS_THRESHOLD", "0.95")
try:
    PASS_THRESHOLD: float = float(_raw_threshold)
    if not (0.0 < PASS_THRESHOLD <= 1.0):
        raise ValueError
except ValueError:
    raise ValueError(
        f"DBT_PASS_THRESHOLD must be a float between 0 (exclusive) and 1 (inclusive). "
        f"Got: '{_raw_threshold}'"
    )


# -- Report output directory ---------------------------------------------------
# Failure reports are written here for orchestrators and alerting pipelines.
REPORTS_DIR = Path(os.getenv("DBT_REPORTS_DIR", str(_project_root / "watermark" / "transform")))


# -- Known acceptable warnings -------------------------------------------------
# These represent documented source-data gaps, not silver logic errors.
# Pipeline treats WARN-only runs as SUCCESS.
# Any warn NOT in this set will be flagged as unexpected and should be investigated.
#
# Last verified: dbt test run — PASS=104 WARN=2 ERROR=0 TOTAL=106
#
#   assert_product_size                — 2 records, tests/silver/assert_product_size.sql
#   not_null_canvas_size_height_inches — 7 records, models/silver/schema.yml
#
KNOWN_WARNS: frozenset[str] = frozenset({
    "assert_product_size",                # 2 records with no matching product size at source
    "not_null_canvas_size_height_inches", # 7 canvas size records missing height at source
})


# -- Custom exception ----------------------------------------------------------
class DataQualityError(RuntimeError):
    """
    Raised when the silver-test pass rate falls below PASS_THRESHOLD.

    Carries the full DbtTestSummary so callers (Airflow callbacks, alert
    handlers, etc.) can inspect the breakdown without re-parsing logs.
    """
    def __init__(self, summary: "DbtTestSummary", threshold: float) -> None:
        self.summary   = summary
        self.threshold = threshold
        super().__init__(
            f"Data-quality gate FAILED: "
            f"pass_rate={summary.pass_rate:.1%}  threshold={threshold:.1%}  "
            f"(PASS={summary.passed} WARN={summary.warned} "
            f"ERROR={summary.errored} TOTAL={summary.total})"
        )


# -- Test result dataclass -----------------------------------------------------
@dataclass
class DbtTestSummary:
    passed:       int = 0
    warned:       int = 0
    errored:      int = 0
    skipped:      int = 0
    total:        int = 0
    failed_tests: list[str] = field(default_factory=list)
    warned_tests: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        """
        Fraction of tests considered passing.

        Both PASS and WARN count as passing — WARNs are documented source-data
        gaps, not silver-logic bugs. SKIP and ERROR do not count as passing.

        Returns 0.0 when total == 0 to avoid ZeroDivisionError.
        """
        if self.total == 0:
            return 0.0
        return (self.passed + self.warned) / self.total

    @property
    def is_clean(self) -> bool:
        """True when there are zero hard errors (warnings are acceptable)."""
        return self.errored == 0

    @property
    def meets_threshold(self) -> bool:
        """True when pass_rate >= PASS_THRESHOLD and there are no hard errors."""
        return self.pass_rate >= PASS_THRESHOLD and self.is_clean

    @property
    def unexpected_warns(self) -> list[str]:
        return [t for t in self.warned_tests if t not in KNOWN_WARNS]


# -- Failure report writer -----------------------------------------------------
def _write_failure_report(
    summary: DbtTestSummary,
    threshold: float,
    run_ts: str,
    log,
) -> Path:
    """
    Persist a JSON failure report to watermark/transform/ and return its path.

    The report is machine-readable so downstream tools (Airflow on_failure
    callbacks, Slack webhooks, PagerDuty integrations) can ingest it without
    parsing log lines.

    Schema:
    {
        "pipeline":        "silver_transform",
        "status":          "DATA_QUALITY_FAILURE",
        "timestamp":       "<ISO-8601>",
        "environment":     "<DBT_TARGET>",
        "pass_rate":       0.91,
        "pass_rate_pct":   "91.0%",
        "threshold":       0.95,
        "threshold_pct":   "95.0%",
        "gap_pct":         "-4.0%",
        "counts": {
            "passed": 455, "warned": 0, "errored": 45,
            "skipped": 0,  "total": 500
        },
        "failed_tests":        [...],
        "warned_tests":        [...],
        "unexpected_warns":    [...]
    }
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts_slug     = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"dq_failure_{ts_slug}.json"

    payload = {
        "pipeline":      "silver_transform",
        "status":        "DATA_QUALITY_FAILURE",
        "timestamp":     run_ts,
        "environment":   DBT_TARGET,
        "pass_rate":     round(summary.pass_rate, 6),
        "pass_rate_pct": f"{summary.pass_rate:.1%}",
        "threshold":     round(threshold, 6),
        "threshold_pct": f"{threshold:.1%}",
        "gap_pct":       f"{(summary.pass_rate - threshold):+.1%}",
        "counts": {
            "passed":  summary.passed,
            "warned":  summary.warned,
            "errored": summary.errored,
            "skipped": summary.skipped,
            "total":   summary.total,
        },
        "failed_tests":     summary.failed_tests,
        "warned_tests":     summary.warned_tests,
        "unexpected_warns": summary.unexpected_warns,
    }

    try:
        with report_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        log.info("Failure report written -> %s", report_path)
    except OSError as exc:
        log.error("Could not write failure report: %s", exc)

    return report_path


# -- dbt executable ------------------------------------------------------------
def _dbt_exe() -> str:
    """Return venv dbt.exe if on Windows, else fall back to PATH 'dbt'."""
    if os.name == "nt":
        venv_dbt = _project_root / ".venv" / "Scripts" / "dbt.exe"
        if venv_dbt.exists():
            return str(venv_dbt)
    return "dbt"


# -- dbt runner ----------------------------------------------------------------
def _run_dbt(args: list[str], log) -> tuple[bool, float, str]:
    """
    Execute a dbt subcommand.

    Returns:
        (success, duration_seconds, captured_stdout)

    success is based purely on dbt's exit code.
    For test steps, call _parse_test_output() to determine true success
    after accounting for acceptable warnings.
    """
    subcommand  = args[0]
    extra_args  = args[1:]

    cmd = [_dbt_exe(), subcommand] + extra_args

    if subcommand in ("run", "snapshot", "test"):
        cmd += ["--target", DBT_TARGET, "--threads", DBT_THREADS]

    log.info("CMD : %s", " ".join(cmd))
    t_start       = datetime.now()
    output_lines: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(DBT_PROJECT_DIR),
        )

        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log.info("  dbt | %s", line)
                output_lines.append(line)

        for line in proc.stderr:
            line = line.rstrip()
            if line:
                log.warning("  dbt [err] | %s", line)

        proc.wait()
        duration = (datetime.now() - t_start).total_seconds()
        success  = proc.returncode == 0
        output   = "\n".join(output_lines)

        if success:
            log.info("finished in %.1fs", duration)
        else:
            log.error("failed (rc=%d) in %.1fs", proc.returncode, duration)

        return success, duration, output

    except FileNotFoundError:
        duration = (datetime.now() - t_start).total_seconds()
        log.error(
            "dbt executable not found.\n"
            "  Install: pip install dbt-postgres  |  uv add dbt-postgres"
        )
        return False, duration, ""

    except Exception as exc:
        duration = (datetime.now() - t_start).total_seconds()
        log.error("Unexpected error running dbt: %s", exc)
        log.debug(traceback.format_exc())
        return False, duration, ""


# -- Test output parser --------------------------------------------------------
def _parse_test_output(output: str, log) -> DbtTestSummary:
    """
    Parse dbt test stdout into a DbtTestSummary.

    Parses the summary line:
        Done. PASS=194 WARN=6 ERROR=0 SKIP=0 NO-OP=0 TOTAL=200

    And individual result lines like:
        38 of 200 FAIL 34 assert_orphan_delivered_orders_without_payments ...
        125 of 200 WARN 19 not_null_product_returns_return_date ...
    """
    summary = DbtTestSummary()

    # Summary counts
    m = re.search(
        r"PASS=(\d+)\s+WARN=(\d+)\s+ERROR=(\d+)\s+SKIP=(\d+).*?TOTAL=(\d+)",
        output,
    )
    if m:
        summary.passed  = int(m.group(1))
        summary.warned  = int(m.group(2))
        summary.errored = int(m.group(3))
        summary.skipped = int(m.group(4))
        summary.total   = int(m.group(5))

    # Individual FAIL lines
    for m in re.finditer(r"\d+ of \d+ FAIL \d+ (\S+)", output):
        name = m.group(1)
        if name not in summary.failed_tests:
            summary.failed_tests.append(name)

    # Individual WARN lines
    for m in re.finditer(r"\d+ of \d+ WARN \d+ (\S+)", output):
        name = m.group(1)
        if name not in summary.warned_tests:
            summary.warned_tests.append(name)

    log.info(
        "Test results -> PASS=%d | WARN=%d | ERROR=%d | SKIP=%d | TOTAL=%d",
        summary.passed, summary.warned, summary.errored, summary.skipped, summary.total,
    )
    log.info(
        "Pass rate    -> %.1f%%  (threshold: %.1f%%)",
        summary.pass_rate * 100,
        PASS_THRESHOLD * 100,
    )

    if summary.warned_tests:
        log.info("Warned tests (%d):", len(summary.warned_tests))
        for t in summary.warned_tests:
            tag = "[known - source gap]" if t in KNOWN_WARNS else "[UNEXPECTED - investigate!]"
            log.info("    WARN  %-60s %s", t, tag)

    if summary.failed_tests:
        log.error("Failed tests (%d):", len(summary.failed_tests))
        for t in summary.failed_tests:
            log.error("    FAIL  %s", t)

    return summary


# -- Data-quality gate ---------------------------------------------------------
def _check_data_quality_gate(
    summary: DbtTestSummary,
    run_ts: str,
    log,
) -> None:
    """
    Enforce the 95% pass-rate threshold gate.

    Decision matrix
    -------------------------------------------------------------------------------
    pass_rate >= 0.95  AND  errored == 0  ->  PASS  (pipeline continues)
    pass_rate >= 0.95  BUT  errored  > 0  ->  FAIL  (hard errors present)
    pass_rate <  0.95  (any errored)      ->  FAIL  (below quality gate)
    -------------------------------------------------------------------------------

    On failure:
      1. Logs a CRITICAL banner with the full breakdown.
      2. Writes a JSON failure report to watermark/transform/ for orchestrators.
      3. Raises DataQualityError (caught by main(), which exits 1).
    """
    gate_ok = summary.meets_threshold
    gap     = summary.pass_rate * 100 - PASS_THRESHOLD * 100

    # Single prominent DQ line — easy to spot in any log viewer
    if gate_ok:
        log.info(
            "DATA QUALITY : %.1f%%  |  THRESHOLD : %.1f%%  |  PASSED  (%+.1f%%)",
            summary.pass_rate * 100,
            PASS_THRESHOLD * 100,
            gap,
        )
    else:
        log.critical(
            "DATA QUALITY : %.1f%%  |  THRESHOLD : %.1f%%  |  FAILED  (%+.1f%%)",
            summary.pass_rate * 100,
            PASS_THRESHOLD * 100,
            gap,
        )

    log.info("-" * 55)
    log.info("DATA QUALITY GATE")
    log.info("  Threshold   : %.1f%%", PASS_THRESHOLD * 100)
    log.info(
        "  Pass rate   : %.1f%%  (%d passing out of %d)",
        summary.pass_rate * 100,
        summary.passed + summary.warned,
        summary.total,
    )
    log.info("  Hard errors : %d", summary.errored)
    log.info("  Result      : %s", "PASSED" if gate_ok else "FAILED")
    log.info("-" * 55)

    if gate_ok:
        return

    # Gate failed
    log.critical("=" * 55)
    log.critical("DATA QUALITY GATE FAILED")
    log.critical("=" * 55)
    log.critical(
        "  pass_rate = %.1f%%   (required >= %.1f%%)",
        summary.pass_rate * 100,
        PASS_THRESHOLD * 100,
    )
    log.critical(
        "  PASS+WARN = %d   ERROR = %d   TOTAL = %d",
        summary.passed + summary.warned,
        summary.errored,
        summary.total,
    )
    log.critical("  Silver layer output is UNTRUSTED.")
    log.critical("  Downstream gold models must NOT run.")
    log.critical("=" * 55)

    if summary.failed_tests:
        log.critical("Failed tests contributing to gate failure:")
        for t in summary.failed_tests:
            log.critical("    FAIL  %s", t)

    if summary.unexpected_warns:
        log.critical("Unexpected warnings (not in KNOWN_WARNS):")
        for t in summary.unexpected_warns:
            log.critical("    WARN  %s", t)

    report_path = _write_failure_report(summary, PASS_THRESHOLD, run_ts, log)
    log.critical("Failure report -> %s", report_path)

    raise DataQualityError(summary, PASS_THRESHOLD)


# -- Main ----------------------------------------------------------------------
def main(full_refresh: bool = False) -> None:
    log    = get_logger(stage="transformation", name="__main__")
    run_ts = datetime.now().strftime(ISO_FMT)

    log.info("==============  TRANSFORM START  ==============")
    log.info("Timestamp   : %s", run_ts)
    log.info("dbt project : %s", DBT_PROJECT_DIR)
    log.info("Target      : %s", DBT_TARGET)
    log.info("Full refresh: %s", full_refresh)
    log.info("DQ threshold: %.1f%%", PASS_THRESHOLD * 100)

    # Sanity: dbt project dir
    if not DBT_PROJECT_DIR.exists():
        log.error("dbt project dir not found: %s", DBT_PROJECT_DIR)
        sys.exit(1)

    # Sanity: Postgres connection
    try:
        from sqlalchemy import text
        engine = postgres_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        log.info(
            "Postgres    : connected  (%s)",
            engine.url.render_as_string(hide_password=True),
        )
        engine.dispose()
    except Exception as exc:
        log.error("Cannot connect to Postgres: %s", exc)
        sys.exit(1)

    # Pipeline steps
    #
    # ORDER IS CRITICAL:
    #   1. snapshot  — SCD Type 2 tables must exist before silver models run
    #   2. run       — silver models read from snapshots + raw sources
    #   3. test      — validate silver after build; gate on 95% pass-rate threshold
    #
    refresh_flag = ["--full-refresh"] if full_refresh else []

    steps: list[tuple[str, list[str], bool]] = [
        # (label,           dbt args,                               is_test_step)
        ("snapshots",       ["snapshot"]           + refresh_flag,  False),
        ("silver models",   ["run", "--select", "silver"] + refresh_flag, False),
        ("silver tests",    ["test", "--select", "silver"],         True),
    ]

    results:      list[tuple[str, bool, float]] = []
    test_summary: DbtTestSummary | None = None

    for label, args, is_test_step in steps:
        log.info("=" * 55)
        log.info("STEP : %s", label)

        raw_success, duration, output = _run_dbt(args, log)

        if is_test_step:
            test_summary = _parse_test_output(output, log)

            try:
                _check_data_quality_gate(test_summary, run_ts, log)
                step_success = True
            except DataQualityError as dq_exc:
                log.error(str(dq_exc))
                step_success = False

        else:
            step_success = raw_success

        results.append((label, step_success, duration))

        if not step_success:
            log.error("Step '%s' failed — stopping pipeline.", label)
            break

    # Run summary
    log.info("")
    log.info("==============  RUN SUMMARY  ==============")

    all_ok     = True
    total_time = 0.0

    for label, success, duration in results:
        status = "OK  " if success else "FAIL"
        log.info("  %-18s  %s  (%.1fs)", label, status, duration)
        total_time += duration
        if not success:
            all_ok = False

    if test_summary and test_summary.total > 0:
        dq_pct    = test_summary.pass_rate * 100
        threshold = PASS_THRESHOLD * 100
        gap       = dq_pct - threshold
        dq_result = "PASSED" if test_summary.meets_threshold else "FAILED"

        log.info("")
        log.info("  =========================================")
        log.info("  DATA QUALITY RESULT")
        log.info("  -----------------------------------------")
        log.info("  DQ score    : %.1f%%", dq_pct)
        log.info("  Threshold   : %.1f%%", threshold)
        log.info("  Gap         : %+.1f%%", gap)
        log.info("  DQ result   : %s", dq_result)
        log.info("  -----------------------------------------")
        log.info("  PASS        : %d", test_summary.passed)
        log.info("  WARN        : %d  (known source gaps)", test_summary.warned)
        log.info("  ERROR       : %d", test_summary.errored)
        log.info("  TOTAL       : %d", test_summary.total)
        log.info("  =========================================")

        if test_summary.unexpected_warns:
            log.warning("")
            log.warning(
                "  %d UNEXPECTED warning(s) not in KNOWN_WARNS — investigate:",
                len(test_summary.unexpected_warns),
            )
            for t in test_summary.unexpected_warns:
                log.warning("      - %s", t)

    log.info("-" * 45)
    log.info("  %-18s        %.1fs", "TOTAL", total_time)
    log.info("  Overall : %s", "PASSED" if all_ok else "FAILED")
    log.info("=" * 45)

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    _full_refresh = "--full-refresh" in sys.argv
    main(full_refresh=_full_refresh)