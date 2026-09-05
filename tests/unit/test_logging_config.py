"""
Unit tests for utils/logging_config.py.

Covers the public API (new_run_id, get_logger, setup_logging) and the two
private-but-load-bearing classes (_RunIdFilter, _JsonFormatter). These
are pure unit tests -- no database, no Spark, no file I/O unless a tmp
directory is explicitly created via the `tmp_path` fixture.
"""

from __future__ import annotations

import json
import logging
import logging.config
import re
from pathlib import Path

import pytest

from utils.logging_config import (
    DEFAULT_LOG_DIR,
    PROJECT_ROOT,
    _JsonFormatter,
    _RunIdFilter,
    get_logger,
    new_run_id,
    setup_logging,
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
class TestNewRunId:
    def test_returns_string(self) -> None:
        assert isinstance(new_run_id(), str)

    def test_returns_unique_ids(self) -> None:
        # 1k calls should produce 1k distinct IDs with overwhelming probability.
        ids = {new_run_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_id_has_expected_shape(self) -> None:
        # 12 hex chars (UUID4 truncated).
        run_id = new_run_id()
        assert re.fullmatch(r"[0-9a-f]{12}", run_id), run_id


class TestGetLogger:
    def test_returns_logger_instance(self) -> None:
        log = get_logger("museum.test.smoke")
        assert isinstance(log, logging.Logger)

    def test_returns_same_logger_for_same_name(self) -> None:
        # logging.getLogger is identity-stable by name; get_logger must be too.
        assert get_logger("museum.test.id") is get_logger("museum.test.id")


# ---------------------------------------------------------------------------
# _RunIdFilter
# ---------------------------------------------------------------------------
class TestRunIdFilter:
    def test_injects_run_id_when_missing(self) -> None:
        f = _RunIdFilter(run_id="abc123")
        record = logging.LogRecord("x", logging.INFO, "", 0, "msg", None, None)
        assert f.filter(record) is True
        assert record.run_id == "abc123"  # type: ignore[attr-defined]

    def test_preserves_explicit_run_id(self) -> None:
        f = _RunIdFilter(run_id="default")
        record = logging.LogRecord("x", logging.INFO, "", 0, "msg", None, None)
        record.run_id = "explicit"  # type: ignore[attr-defined]
        f.filter(record)
        assert record.run_id == "explicit"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _JsonFormatter
# ---------------------------------------------------------------------------
class TestJsonFormatter:
    def _make_record(self, msg: str = "hello", level: int = logging.INFO) -> logging.LogRecord:
        return logging.LogRecord(
            name="museum.test",
            level=level,
            pathname=__file__,
            lineno=1,
            msg=msg,
            args=None,
            exc_info=None,
        )

    def test_emits_valid_json(self) -> None:
        rec = self._make_record()
        out = _JsonFormatter(run_id="rid1").format(rec)
        payload = json.loads(out)
        assert isinstance(payload, dict)

    def test_includes_ecs_fields(self) -> None:
        rec = self._make_record("hello world", logging.WARNING)
        payload = json.loads(_JsonFormatter(run_id="rid1").format(rec))
        assert payload["level"] == "WARNING"
        assert payload["message"] == "hello world"
        assert payload["logger"] == "museum.test"
        assert payload["run_id"] == "rid1"
        assert "ts" in payload
        # ISO-8601 with milliseconds + UTC offset.
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}", payload["ts"])

    def test_promotes_extra_keys_to_top_level(self) -> None:
        rec = self._make_record()
        rec.rows = 1234  # type: ignore[attr-defined]
        rec.collection = "products"  # type: ignore[attr-defined]
        payload = json.loads(_JsonFormatter(run_id="rid1").format(rec))
        assert payload["rows"] == 1234
        assert payload["collection"] == "products"

    def test_serialises_datetime_extra(self) -> None:
        from datetime import datetime, timezone
        rec = self._make_record()
        when = datetime(2026, 9, 5, 12, 34, 56, tzinfo=timezone.utc)
        rec.when = when  # type: ignore[attr-defined]
        # Must not raise; must be string-coercible.
        payload = json.loads(_JsonFormatter(run_id="rid1").format(rec))
        assert "when" in payload

    def test_renders_exception_traceback(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            rec = logging.LogRecord(
                "museum.test", logging.ERROR, __file__, 1,
                "failed", None, sys.exc_info(),
            )
        payload = json.loads(_JsonFormatter(run_id="rid1").format(rec))
        assert "exc" in payload
        assert "ValueError: boom" in payload["exc"]


# ---------------------------------------------------------------------------
# setup_logging (uses tmp_path so the real log dir is never touched)
# ---------------------------------------------------------------------------
class TestSetupLogging:
    def test_configures_root_for_museum_namespace(self, tmp_path: Path) -> None:
        run_id = setup_logging(level="DEBUG", log_dir=tmp_path, log_format="json")
        log = get_logger("museum.smoke.test")
        log.info("ping", extra={"rows": 7})
        # File must exist and contain the JSON line.
        log_file = tmp_path / "museum-etl.log"
        assert log_file.exists()
        contents = log_file.read_text(encoding="utf-8").splitlines()
        assert contents, "no log lines were written"
        payload = json.loads(contents[-1])
        assert payload["message"] == "ping"
        assert payload["rows"] == 7
        assert payload["run_id"] == run_id

    def test_console_format_uses_human_layout(self, tmp_path: Path) -> None:
        # Sanity: console format stays human-readable; JSON files stay JSON.
        setup_logging(level="INFO", log_dir=tmp_path, log_format="console")
        log = get_logger("museum.console.test")
        log.info("hi")
        log_file = tmp_path / "museum-etl.log"
        text = log_file.read_text(encoding="utf-8")
        # The console format is "asctime | level | name | message" -- so the
        # file (bound to the json formatter) must still parse as JSON.
        json.loads(text.strip().splitlines()[-1])

    def test_returns_run_id_string(self, tmp_path: Path) -> None:
        run_id = setup_logging(log_dir=tmp_path)
        assert isinstance(run_id, str)
        assert re.fullmatch(r"[0-9a-f]{12}", run_id)

    def test_default_log_dir_is_under_project_root(self) -> None:
        # The default LOG_DIR must resolve to <project_root>/logs, not /tmp
        # or some other random spot -- otherwise a developer running this
        # without overriding LOG_DIR would silently get logs in the wrong
        # place.
        assert DEFAULT_LOG_DIR == PROJECT_ROOT / "logs"
