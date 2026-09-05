"""
Unit tests for scripts/python/dbt_runner.py.

Covers pure helpers (`find_project_root`, `parse_args`, the
`StageResult` dataclass) without actually invoking dbt. The dbt subprocess
calls are exercised only in the real pipeline run; here we just need to
guarantee the building blocks behave correctly.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pytest
from rich.console import Console

from scripts.python import dbt_runner


@pytest.fixture
def tmp_console() -> Console:
    # Force Console to write to the null device so test output stays clean.
    # Use os.devnull because /dev/null doesn't exist on Windows.
    return Console(file=open(os.devnull, "w"), force_terminal=False)


class TestFindProjectRoot:
    def test_finds_dbt_project_in_current_dir(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_project.yml").write_text("name: test\n")
        assert dbt_runner.find_project_root(tmp_path) == tmp_path

    def test_walks_up_to_find_dbt_project(self, tmp_path: Path) -> None:
        (tmp_path / "dbt_project.yml").write_text("name: test\n")
        nested = tmp_path / "models" / "staging"
        nested.mkdir(parents=True)
        assert dbt_runner.find_project_root(nested) == tmp_path

    def test_falls_back_to_sibling_subdir(self, tmp_path: Path, tmp_console: Console, monkeypatch) -> None:
        # When the script is launched from a parent dir that has a dbt_project
        # somewhere in its children, find_project_root should pick that up.
        dbt_dir = tmp_path / "museum_dbt"
        dbt_dir.mkdir()
        (dbt_dir / "dbt_project.yml").write_text("name: test\n")
        sibling = tmp_path / "scripts"
        sibling.mkdir()
        # The sibling is the start; parent is tmp_path; child dbt dir is found.
        assert dbt_runner.find_project_root(sibling) == dbt_dir

    def test_errors_when_no_project_found(self, tmp_path: Path, tmp_console: Console, monkeypatch, capsys) -> None:
        # Run from a directory with no dbt_project.yml anywhere up the tree.
        # We must NOT raise; we must sys.exit(1) with a useful message.
        empty = tmp_path / "nowhere"
        empty.mkdir()
        with pytest.raises(SystemExit) as exc_info:
            dbt_runner.find_project_root(empty)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Could not locate dbt_project.yml" in captured.out


class TestParseArgs:
    def test_defaults(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "argv", ["dbt_runner.py"])
        ns = dbt_runner.parse_args()
        assert ns.project_dir is None
        assert ns.skip_tests is False
        assert ns.silver_only is False
        assert ns.gold_only is False
        assert ns.full_refresh is False

    def test_all_flags(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "argv", [
            "dbt_runner.py",
            "--project-dir", "/tmp/dbt",
            "--skip-tests",
            "--silver-only",
            "--full-refresh",
        ])
        ns = dbt_runner.parse_args()
        assert ns.project_dir == Path("/tmp/dbt")
        assert ns.skip_tests is True
        assert ns.silver_only is True
        assert ns.gold_only is False
        assert ns.full_refresh is True


class TestStageResult:
    def test_construction(self, tmp_path: Path) -> None:
        result = dbt_runner.StageResult(
            name="silver_run",
            command="uv run dbt run --select tag:silver",
            success=True,
            duration_seconds=1.23,
            log_path=tmp_path / "silver_run.log",
        )
        assert result.name == "silver_run"
        assert result.success is True
        assert result.duration_seconds == 1.23
        assert result.log_path == tmp_path / "silver_run.log"


class TestConstants:
    def test_selectors_are_tag_based(self) -> None:
        # The whole pipeline assumes tag:silver and tag:gold. If anyone ever
        # renames a tag in dbt without updating the runner, this will catch it.
        assert dbt_runner.SILVER_SELECTOR == "tag:silver"
        assert dbt_runner.GOLD_SELECTOR == "tag:gold"

    def test_log_dir_name_is_logs(self) -> None:
        # The PowerShell + Python + bash runners all agree on a "logs" dir.
        assert dbt_runner.LOG_DIR_NAME == "logs"
