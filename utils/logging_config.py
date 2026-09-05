"""
utils/logging_config.py
=======================

Industry-standard logging for the museum-etl pipeline.

DESIGN PRINCIPLES
-----------------
This module follows the patterns recommended in PEP 282, the Python
logging cookbook, and 12-factor app methodology. It is intentionally
written as a single, opinionated configuration so every script in the
project gets consistent log output without each one re-implementing
handler setup.

1. **Configured once, imported everywhere.**  We use the standard
   `logging.config.dictConfig` so the entire pipeline can be reconfigured
   from one place (e.g. a different LOG_LEVEL env var in CI).

2. **JSON for files, human-readable for the console.**  Production logs
   are structured JSON, one event per line, so they're easy to ship to
   any log aggregator (ELK, Loki, Datadog) without a parser. The console
   handler keeps the colourless, single-line format humans actually read.

3. **Log rotation, not unbounded growth.**  `RotatingFileHandler` caps
   each log file at 10 MB and keeps 5 backups. Without this, a long-
   running incremental.py could fill the disk on a cron run that nobody
   checks for months.

4. **Correlation IDs.**  Every run gets a UUID. Every log record carries
   it. A single failure can be traced across stages (bronze -> silver ->
   gold) by grepping the same `run_id` in every log file -- the same
   pattern Airflow uses with its `dag_run.run_id`.

5. **`extra=` is the public API.**  Callers pass structured data via
   `logger.info("loaded batch", extra={"rows": 1234, "collection": "x"})`
   and the JSON handler serialises it. This avoids string-concatenating
   row counts into messages (which kills log searchability).

6. **No global side effects on import.**  Calling `get_logger(__name__)`
   does NOT call `dictConfig`. We expose `setup_logging()` as a separate
   entry point that the pipeline's top-level orchestrators (main.py, the
   DAG) call once at startup. Library code (utils/engine.py) just calls
   `get_logger(__name__)` and inherits the configuration.

7. **`propagate = False` on the root.**  We don't want our messages
   double-printed because the user also did `logging.basicConfig()` in
   their notebook. The pipeline owns the logging config; nothing else.

USAGE
-----
    # At the top of main.py / the DAG:
    from utils.logging_config import setup_logging, new_run_id
    setup_logging(level="INFO")
    log = get_logger(__name__)
    log.info("pipeline start", extra={"run_id": new_run_id()})

    # In any other module:
    from utils.logging_config import get_logger
    log = get_logger(__name__)
    log.info("loaded batch", extra={"rows": 1234})

ENVIRONMENT VARIABLES
---------------------
    LOG_LEVEL      - DEBUG, INFO, WARNING, ERROR. Default: INFO.
    LOG_DIR        - Where log files are written. Default: <project>/logs
    LOG_FORMAT     - "json" (default) or "console" for a friendlier
                     single-line human format.
    LOG_MAX_BYTES  - Per-file rotation size. Default: 10_485_760 (10 MB).
    LOG_BACKUP_COUNT - How many rotated backups to keep. Default: 5.
"""

from __future__ import annotations

import json
import logging
import logging.config
import os
import sys
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
# utils/logging_config.py lives at <project_root>/utils/logging_config.py,
# so the project root is one level up. We resolve this once at import time
# so subsequent log calls don't re-walk the path.
_UTILS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _UTILS_DIR.parent

# Default log directory. Override with LOG_DIR env var. The directory is
# created on demand by setup_logging() so callers don't have to.
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"

# Whether dictConfig has been applied. We track this so repeated calls
# to setup_logging() (e.g. the DAG re-running a task) don't stack
# duplicate handlers.
_CONFIGURED = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def new_run_id() -> str:
    """Return a fresh, URL-safe run identifier. Call once at the top of a
    pipeline run and pass it via `extra={"run_id": ...}` on every log
    record so the full trace of a single run is searchable later."""
    return uuid.uuid4().hex[:12]


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name. This is a thin wrapper
    over `logging.getLogger` so callers can adopt it without re-writing
    their imports; it also gives us one place to add per-module
    behaviour later (e.g. sampling, redaction) if needed."""
    return logging.getLogger(name)


def setup_logging(
    level: str | int | None = None,
    log_dir: str | os.PathLike[str] | None = None,
    log_format: str | None = None,
    run_id: str | None = None,
) -> str:
    """Configure the project's logging. Idempotent: safe to call multiple
    times (re-running tasks in the DAG, for example). Returns the run_id
    that was bound, so callers can echo it into their own bookkeeping."""
    global _CONFIGURED

    # ------------------------------------------------------------------
    # Resolve configuration: explicit args win, then env, then defaults.
    # ------------------------------------------------------------------
    level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    log_format = (log_format or os.getenv("LOG_FORMAT", "json")).lower()
    log_dir = Path(log_dir or os.getenv("LOG_DIR", DEFAULT_LOG_DIR))
    max_bytes = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "5"))
    run_id = run_id or new_run_id()

    log_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Build the dictConfig payload.
    # ------------------------------------------------------------------
    # Two formatters:
    #   - "json" : one JSON object per line, machine-readable.
    #   - "console" : single line, human-readable, includes level and
    #                timestamp in the order operators expect.
    # Two handlers per format:
    #   - "file" : rotating JSON file in <log_dir>/museum-etl.log
    #   - "stderr" : stream to stderr (NOT stdout -- mixing logs with
    #                real output breaks downstream pipe composition).
    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "run_id": {
                "()": _RunIdFilter,
                "run_id": run_id,
            },
        },
        "formatters": {
            "json": {
                "()": _JsonFormatter,
                "run_id": run_id,
            },
            "console": {
                "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S%z",
            },
        },
        "handlers": {
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_dir / "museum-etl.log"),
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
                "formatter": "json",
                "filters": ["run_id"],
                "level": "DEBUG",
            },
            "stderr": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
                "formatter": "console" if log_format == "console" else "json",
                "filters": ["run_id"],
                "level": level,
            },
        },
        "loggers": {
            # Project logger: catch every record emitted under our namespace
            # without having to enumerate modules. The DAG's library code
            # uses "airflow.*" loggers and is handled by Airflow itself.
            "museum": {
                "handlers": ["file", "stderr"],
                "level": "DEBUG",
                "propagate": False,
            },
            # Tame noisy third-party loggers. Without this, py4j / pyspark /
            # urllib3 / sqlalchemy will drown out our INFO output.
            "py4j": {"level": "WARNING"},
            "pyspark": {"level": "WARNING"},
            "urllib3": {"level": "WARNING"},
            "sqlalchemy.engine": {"level": "WARNING"},
            "dbt": {"level": "INFO"},
        },
        "root": {
            "handlers": [],
            "level": "WARNING",
        },
    }

    logging.config.dictConfig(config)
    _CONFIGURED = True

    # Echo a single banner so operators can see the run_id immediately
    # without grepping the log file. This deliberately goes to stderr
    # (the same stream as all subsequent log output).
    banner = logging.getLogger("museum.startup")
    banner.info(
        "logging configured",
        extra={
            "run_id": run_id,
            "level": level,
            "format": log_format,
            "log_dir": str(log_dir),
        },
    )

    return run_id


# ---------------------------------------------------------------------------
# Custom filter & formatter
# ---------------------------------------------------------------------------
class _RunIdFilter(logging.Filter):
    """Inject `run_id` into every log record so the JSON formatter can
    include it without callers having to remember to pass it as `extra=`
    on every log call. If a record already carries a `run_id` in its
    `extra` (e.g. caller explicitly set it), we keep that instead."""

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "run_id", None):
            record.run_id = self.run_id
        return True


class _JsonFormatter(logging.Formatter):
    """Render every log record as one JSON object per line. The shape
    is deliberately close to the ECS / Logstash conventions so it's
    drop-in for most log aggregators without a custom parser:

        {"ts":"2026-09-05T12:34:56.789Z",
         "level":"INFO",
         "logger":"museum.etl.bronze",
         "message":"loaded batch",
         "run_id":"a1b2c3d4e5f6",
         "rows":1234,
         "collection":"products"}

    Any key passed via `extra=` lands at the top level of the JSON
    object, so `logger.info("...", extra={"rows": 1234})` produces
    `"rows": 1234` in the output without any extra plumbing."""

    # Standard LogRecord attributes that we never want duplicated under
    # their own JSON key. Anything *not* in this set AND not in the
    # built-in LogRecord namespace is treated as caller-supplied `extra`.
    _STANDARD_ATTRS = frozenset({
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "asctime", "run_id",
    })

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def format(self, record: logging.LogRecord) -> str:
        # Base payload. `message` is the rendered log message; `getMessage`
        # applies %-formatting if `args` was passed.
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "run_id": getattr(record, "run_id", self.run_id),
        }

        # Append any caller-supplied `extra=` keys. We compare against
        # the standard LogRecord attribute set so we don't accidentally
        # leak internal fields like `process` or `thread` as separate
        # top-level keys (they're not interesting for ETL log search).
        for key, value in record.__dict__.items():
            if key in self._STANDARD_ATTRS or key.startswith("_"):
                continue
            # JSON doesn't know about datetime/Path/Enum -- serialise them
            # to their string form. Anything truly exotic will fall back
            # to repr() so we never crash the log handler.
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        # If an exception was attached, render its traceback into a
        # nested field rather than the standard "exc_info" tuple.
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Backwards compatibility shim
# ---------------------------------------------------------------------------
# The pre-refactor codebase imported `from utils.logger import get_logger`
# and used the signature `get_logger(stage: str, name: str)`. We keep a
# thin shim so existing modules (utils/engine.py, etc.) keep working
# without any import-site changes -- the shim logs a deprecation hint
# the first time it's used so future cleanup is visible.
def get_logger_compat(stage: str, name: str) -> logging.Logger:  # pragma: no cover
    """Backwards-compatible shim for the old `get_logger(stage, name)`
    signature. New code should use `get_logger(name)`."""
    new_name = f"museum.{stage}.{name}" if stage else f"museum.{name}"
    log = logging.getLogger(new_name)
    if not getattr(get_logger_compat, "_warned", False):
        log.debug(
            "get_logger(stage, name) is deprecated; use get_logger(name) instead",
        )
        get_logger_compat._warned = True
    return log


__all__ = [
    "get_logger",
    "new_run_id",
    "setup_logging",
    "PROJECT_ROOT",
    "DEFAULT_LOG_DIR",
]
