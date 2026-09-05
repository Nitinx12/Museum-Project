"""
Unit tests for scripts/python/run_sql_tests.py.

Covers the layer/test discovery helpers and the `TestResult` dataclass
without actually executing any SQL against a database. SQL execution is
exercised only in the real pipeline; these tests pin the discovery
behaviour and the PREFERRED_LAYER_ORDER contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.python import run_sql_tests
from scripts.python.run_sql_tests import (
    PREFERRED_LAYER_ORDER,
    SQLTestSuiteFailed,
    discover_layers,
    discover_tests,
)
# Imported under an alias to avoid pytest trying to collect the production
# dataclass as a test class (its name starts with "Test").
from scripts.python.run_sql_tests import TestResult as SqlTestResult


# ---------------------------------------------------------------------------
# Layer + test discovery
# ---------------------------------------------------------------------------
class TestDiscoverLayers:
    def test_returns_only_directories(self, tmp_path: Path) -> None:
        (tmp_path / "bronze").mkdir()
        (tmp_path / "silver").mkdir()
        (tmp_path / "readme.md").write_text("not a layer")
        layers = discover_layers(tmp_path)
        assert {p.name for p in layers} == {"bronze", "silver"}

    def test_preferred_order_is_bronze_silver_gold_then_alphabetical(self, tmp_path: Path) -> None:
        # Create folders in NON-preferred order to confirm ordering is by name,
        # not filesystem order.
        (tmp_path / "gold").mkdir()
        (tmp_path / "bronze").mkdir()
        (tmp_path / "silver").mkdir()
        (tmp_path / "audit").mkdir()
        layers = discover_layers(tmp_path)
        names = [p.name for p in layers]
        # Known layers come first in PREFERRED_LAYER_ORDER; "audit" comes after.
        assert names == ["bronze", "silver", "gold", "audit"]

    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        assert discover_layers(tmp_path) == []


class TestDiscoverTests:
    def test_finds_sql_files_in_subtree(self, tmp_path: Path) -> None:
        (tmp_path / "check_a.sql").write_text("--")
        sub = tmp_path / "nested"
        sub.mkdir()
        (sub / "check_b.sql").write_text("--")
        results = discover_tests(tmp_path)
        assert len(results) == 2
        assert all(p.suffix == ".sql" for p in results)
        # Sorted.
        assert results == sorted(results)

    def test_ignores_non_sql_files(self, tmp_path: Path) -> None:
        (tmp_path / "check.sql").write_text("--")
        (tmp_path / "notes.md").write_text("not a test")
        (tmp_path / "README.txt").write_text("not a test")
        assert len(discover_tests(tmp_path)) == 1


# ---------------------------------------------------------------------------
# TestResult dataclass
# ---------------------------------------------------------------------------
class TestSqlTestResult:
    def test_defaults(self, tmp_path: Path) -> None:
        r = SqlTestResult(layer="bronze", name="check_x", path=tmp_path / "x.sql",
                            status="PASS", seconds=0.5)
        assert r.message == ""

    def test_explicit_message(self, tmp_path: Path) -> None:
        r = SqlTestResult(layer="silver", name="check_y", path=tmp_path / "y.sql",
                            status="FAIL", seconds=1.0, message="oops")
        assert r.status == "FAIL"
        assert r.message == "oops"


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_preferred_layer_order(self) -> None:
        assert PREFERRED_LAYER_ORDER == ["bronze", "silver", "gold"]

    def test_log_dir_name(self) -> None:
        assert run_sql_tests.LOG_DIR_NAME == "logs"


class TestSqlTestSuiteFailed:
    def test_is_exception(self) -> None:
        assert issubclass(SQLTestSuiteFailed, Exception)

    def test_carries_message(self) -> None:
        exc = SQLTestSuiteFailed("3 failed: x, y, z")
        assert "3 failed" in str(exc)
