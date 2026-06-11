"""
load.py

Gold-layer loading pipeline.

Step order:
  1. dbt run   gold      <- gold models built from silver layer
  2. dbt test  gold      <- 41 tests; 0 known WARNs

Gold models:
  dim_artist, dim_artwork, dim_canvas_size, dim_museum, fct_sales

Known acceptable warnings:
  None — gold layer currently has no documented source-data gaps.
  Any WARN in gold is unexpected and will be flagged for investigation.

Pass-rate gate:
  Pipeline is marked SUCCESS only when:
    (passed + warned) / total  >=  PASS_THRESHOLD   (default 0.95 / 95%)
  Override at runtime:
    DBT_PASS_THRESHOLD=0.90 python -m scripts.loading.load

  Current baseline (last clean run):
    PASS=41  WARN=0  ERROR=0  SKIP=0  NO-OP=0  TOTAL=41  ->  pass_rate=100.0%  PASSED

  On failure the pipeline:
    1. Logs a CRITICAL data-quality alert with the breakdown
    2. Writes a JSON failure report to <project_root>/watermark/gold/dq_failure_<timestamp>.json
    3. Exits with code 1 to fail any upstream orchestrator (Airflow, etc.)

Usage:
    python -m scripts.loading.load
    python -m scripts.loading.load --full-refresh

Environment variables:
    DBT_PROJECT_DIR   — path to the dbt project (default: <project_root>/museum_dbt)
    DBT_PROFILES_DIR  — path to dbt profiles directory (default: ~/.dbt)
    DBT_TARGET        — dbt target profile (default: dev)
    DBT_THREADS       — dbt thread count (default: 4)
    DBT_PASS_THRESHOLD — DQ gate threshold as a float 0–1 (default: 0.95)
    DBT_REPORTS_DIR   — failure report output dir (default: <project_root>/watermark/gold)
    PROJECT_ROOT      — override auto-detected project root
"""

from __future__ import annotations

import json
import os
import queue
import re
import sys
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


# -- sys.path fix --------------------------------------------------------------
def _find_project_root() -> Path | None:
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "pyproject.toml").exists() or (current / "main.py").exists():
            return current
        current = current.parent
    return None


def _find_scripts_root() -> Path | None:
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "utils" / "engine.py").exists():
            return current
        if (current / "scripts" / "utils" / "engine.py").exists():
            return current / "scripts"
        current = current.parent
    return None


_project_root = _find_project_root()
if _project_root is None:
    env_root = os.getenv("PROJECT_ROOT")
    _project_root = Path(env_root) if env_root else Path("/opt/airflow/project")

_scripts_root = _find_scripts_root()
if _scripts_root is None:
    _scripts_root = Path("/opt/airflow/project/scripts")

if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))


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
# PASS + WARN both count as passing.
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
REPORTS_DIR = Path(os.getenv("DBT_REPORTS_DIR", str(_project_root / "watermark" / "gold")))


# -- Known acceptable warnings -------------------------------------------------
# Gold layer currently has no documented source-data gaps.
# Any WARN here is unexpected and should be investigated immediately.
#
# Last verified: dbt test --select gold — PASS=41 WARN=0 ERROR=0 TOTAL=41
#
KNOWN_WARNS: frozenset[str] = frozenset()


# -- Custom exception ----------------------------------------------------------
class DataQualityError(RuntimeError):
    """
    Raised when the gold-test pass rate falls below PASS_THRESHOLD.

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
    no_op:        int = 0   # FIX 4: capture NO-OP count from dbt summary line
    total:        int = 0
    failed_tests: list[str] = field(default_factory=list)
    warned_tests: list[str] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.passed + self.warned) / self.total

    @property
    def is_clean(self) -> bool:
        return self.errored == 0

    @property
    def meets_threshold(self) -> bool:
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
    Persist a JSON failure report to watermark/gold/ and return its path.

    Schema:
    {
        "pipeline":        "gold_load",
        "status":          "DATA_QUALITY_FAILURE",
        "timestamp":       "<ISO-8601>",
        "environment":     "<DBT_TARGET>",
        "pass_rate":       0.91,
        "pass_rate_pct":   "91.0%",
        "threshold":       0.95,
        "threshold_pct":   "95.0%",
        "gap_pct":         "-4.0%",
        "counts": { "passed": ..., "warned": ..., "errored": ..., "no_op": ..., ... },
        "failed_tests":     [...],
        "warned_tests":     [...],
        "unexpected_warns": [...]
    }
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts_slug     = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"dq_failure_{ts_slug}.json"

    payload = {
        "pipeline":      "gold_load",
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
            "no_op":   summary.no_op,   # FIX 4: included in failure report
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
    if os.name == "nt":
        venv_dbt = _project_root / ".venv" / "Scripts" / "dbt.exe"
        if venv_dbt.exists():
            return str(venv_dbt)
    return "dbt"


# -- dbt runner ----------------------------------------------------------------
def _run_dbt(args: list[str], log) -> tuple[bool, float, str]:
    """
    Execute a dbt subcommand and stream its output in real time.

    stdout lines are collected and returned for parsing.
    stderr lines are logged at WARNING level.

    Both streams are drained concurrently by background threads to prevent
    the subprocess pipe buffer from filling and deadlocking (FIX 1).

    --profiles-dir is always forwarded to dbt run/test so the
    DBT_PROFILES_DIR env var is actually respected (FIX 3).

    Returns:
        (success, duration_seconds, captured_stdout)
    """
    subcommand = args[0]
    extra_args = args[1:]

    cmd = [_dbt_exe(), subcommand] + extra_args

    # FIX 3: forward --profiles-dir so DBT_PROFILES_DIR is respected
    if subcommand in ("run", "test"):
        cmd += [
            "--target",        DBT_TARGET,
            "--threads",       DBT_THREADS,
            "--profiles-dir",  str(DBT_PROFILES_DIR),
        ]

    log.info("CMD : %s", " ".join(cmd))
    t_start = datetime.now()

    # FIX 1: drain stdout and stderr on separate threads to prevent deadlock.
    # Reading one stream synchronously while the other fills its OS pipe buffer
    # causes the subprocess to block, which in turn causes this process to block.
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    drain_q: queue.Queue[None] = queue.Queue()

    def _drain(stream, collector: list[str], log_fn) -> None:
        try:
            for raw in stream:
                line = raw.rstrip()
                if line:
                    log_fn(line)
                    collector.append(line)
        finally:
            drain_q.put(None)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(DBT_PROJECT_DIR),
        )

        stdout_thread = threading.Thread(
            target=_drain,
            args=(
                proc.stdout,
                stdout_lines,
                lambda line: log.info("  dbt | %s", line),
            ),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_drain,
            args=(
                proc.stderr,
                stderr_lines,
                lambda line: log.warning("  dbt [err] | %s", line),
            ),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        # Wait for both drain threads to finish before calling proc.wait()
        # so we never block on pipe I/O after the process exits.
        drain_q.get()
        drain_q.get()
        stdout_thread.join()
        stderr_thread.join()

        proc.wait()
        duration = (datetime.now() - t_start).total_seconds()
        success  = proc.returncode == 0
        output   = "\n".join(stdout_lines)

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
        log.error("Unexpected error running dbt: %s", exc, exc_info=True)  # FIX (minor): exc_info replaces manual traceback.format_exc at DEBUG
        return False, duration, ""


# -- Test output parser --------------------------------------------------------
def _parse_test_output(output: str, log) -> DbtTestSummary:
    """
    Parse dbt test stdout into a DbtTestSummary.

    Parses the summary line:
        Done. PASS=41 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=41

    FIX 2: if the summary line cannot be matched, a WARNING is emitted
    immediately so a parse failure is never mistaken for a clean run
    (total=0 → pass_rate=0.0 → gate FAILED, but the root cause would
    otherwise be invisible in the logs).

    FIX 4: NO-OP count is now captured and stored on the summary so the
    per-field counts always reconcile with TOTAL.
    """
    summary = DbtTestSummary()

    # FIX 4: extended regex to also capture NO-OP between SKIP and TOTAL
    m = re.search(
        r"PASS=(\d+)\s+WARN=(\d+)\s+ERROR=(\d+)\s+SKIP=(\d+)"
        r"(?:\s+NO-OP=(\d+))?"   # optional — older dbt versions omit NO-OP
        r".*?TOTAL=(\d+)",
        output,
    )
    if m:
        summary.passed  = int(m.group(1))
        summary.warned  = int(m.group(2))
        summary.errored = int(m.group(3))
        summary.skipped = int(m.group(4))
        summary.no_op   = int(m.group(5) or 0)   # FIX 4: default 0 if absent
        summary.total   = int(m.group(6))
    else:
        # FIX 2: explicit parse-failure warning — never silently returns zeros
        log.warning(
            "Could not parse dbt test summary line from output. "
            "The dbt output format may have changed, or dbt produced no output. "
            "DQ gate will treat this as total=0 and FAIL the pipeline."
        )

    for fm in re.finditer(r"\d+ of \d+ FAIL \d+ (\S+)", output):
        name = fm.group(1)
        if name not in summary.failed_tests:
            summary.failed_tests.append(name)

    for wm in re.finditer(r"\d+ of \d+ WARN \d+ (\S+)", output):
        name = wm.group(1)
        if name not in summary.warned_tests:
            summary.warned_tests.append(name)

    log.info(
        "Test results -> PASS=%d | WARN=%d | ERROR=%d | SKIP=%d | NO-OP=%d | TOTAL=%d",
        summary.passed, summary.warned, summary.errored,
        summary.skipped, summary.no_op, summary.total,
    )
    log.info(
        "Pass rate    -> %.1f%%  (threshold: %.1f%%)",
        summary.pass_rate * 100,
        PASS_THRESHOLD * 100,
    )

    if summary.warned_tests:
        log.warning("Warned tests (%d):", len(summary.warned_tests))
        for t in summary.warned_tests:
            tag = "[known - source gap]" if t in KNOWN_WARNS else "[UNEXPECTED - investigate!]"
            log.warning("    WARN  %-60s %s", t, tag)

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
      2. Writes a JSON failure report to watermark/gold/ for orchestrators.
      3. Raises DataQualityError (caught by main(), which exits 1).
    """
    gate_ok = summary.meets_threshold
    gap     = summary.pass_rate * 100 - PASS_THRESHOLD * 100

    # Single prominent DQ line
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
    log.critical("  Gold layer output is UNTRUSTED.")
    log.critical("  Downstream consumers must NOT use this data.")
    log.critical("=" * 55)

    if summary.failed_tests:
        log.critical("Failed tests contributing to gate failure:")
        for t in summary.failed_tests:
            log.critical("    FAIL  %s", t)

    if summary.unexpected_warns:
        log.critical("Unexpected warnings (gold layer should have zero warns):")
        for t in summary.unexpected_warns:
            log.critical("    WARN  %s", t)

    report_path = _write_failure_report(summary, PASS_THRESHOLD, run_ts, log)
    log.critical("Failure report -> %s", report_path)

    raise DataQualityError(summary, PASS_THRESHOLD)


# -- Main ----------------------------------------------------------------------
def main(full_refresh: bool = False) -> None:
    log    = get_logger(stage="loading", name="__main__")
    run_ts = datetime.now().strftime(ISO_FMT)

    log.info("==============  LOAD START  ==============")
    log.info("Timestamp   : %s", run_ts)
    log.info("dbt project : %s", DBT_PROJECT_DIR)
    log.info("Profiles dir: %s", DBT_PROFILES_DIR)
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
    # Gold reads directly from silver — no snapshot step needed.
    #   1. run   — gold models read from silver layer
    #   2. test  — validate gold after build; gate on 95% pass-rate threshold
    #
    refresh_flag = ["--full-refresh"] if full_refresh else []

    steps: list[tuple[str, list[str], bool]] = [
        # (label,         dbt args,                             is_test_step)
        ("gold models",   ["run", "--select", "gold"] + refresh_flag, False),
        ("gold tests",    ["test", "--select", "gold"],               True),
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
        log.info("  WARN        : %d", test_summary.warned)
        log.info("  ERROR       : %d", test_summary.errored)
        log.info("  NO-OP       : %d", test_summary.no_op)
        log.info("  TOTAL       : %d", test_summary.total)
        log.info("  =========================================")

        if test_summary.unexpected_warns:
            log.warning("")
            log.warning(
                "  %d UNEXPECTED warning(s) — gold layer should have zero warns:",
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