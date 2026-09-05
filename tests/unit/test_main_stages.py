"""
Unit tests for the main.py stage construction logic.

We deliberately avoid invoking `uv run` against the real scripts (that
would need Postgres + Mongo running). Instead we exercise the pure
function that maps CLI flags to a list of `Stage` objects, then assert
on shape -- which command, which script path, whether a stage is present
or absent given the flags.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from main import build_stages, Stage


def _ns(**overrides) -> argparse.Namespace:
    """Build a minimal Namespace mirroring main.parse_args' defaults."""
    base = dict(
        skip_tests=False,
        bronze_only=False,
        full=False,
        layers=["bronze", "silver", "gold"],
        dry_run=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class TestBuildStages:
    def test_full_default_pipeline_includes_all_four_stages(self) -> None:
        stages = build_stages(_ns())
        names = [s.name for s in stages]
        assert names == ["bronze_load", "test_bronze", "build_silver_gold", "test_silver_gold"]

    def test_skip_tests_drops_both_test_stages(self) -> None:
        stages = build_stages(_ns(skip_tests=True))
        names = [s.name for s in stages]
        assert "test_bronze" not in names
        assert "test_silver_gold" not in names
        # Bronze load + silver/gold build must still both run.
        assert "bronze_load" in names
        assert "build_silver_gold" in names

    def test_bronze_only_stops_after_bronze(self) -> None:
        stages = build_stages(_ns(bronze_only=True))
        names = [s.name for s in stages]
        assert "bronze_load" in names
        assert "test_bronze" in names
        assert "build_silver_gold" not in names
        assert "test_silver_gold" not in names

    def test_bronze_only_with_skip_tests_runs_just_bronze_load(self) -> None:
        stages = build_stages(_ns(bronze_only=True, skip_tests=True))
        assert [s.name for s in stages] == ["bronze_load"]

    def test_layer_filter_bronze_only_runs_no_silver_gold(self) -> None:
        stages = build_stages(_ns(layers=["bronze"]))
        names = [s.name for s in stages]
        assert "bronze_load" in names
        assert "test_bronze" in names
        assert "build_silver_gold" not in names
        assert "test_silver_gold" not in names

    def test_layer_filter_silver_only_skips_bronze(self) -> None:
        stages = build_stages(_ns(layers=["silver"]))
        # bronze_load is unconditional; --layers bronze only affects the test.
        assert "bronze_load" in stages[0].uv_args or stages[0].name == "bronze_load"
        # But the bronze test should NOT run.
        assert all(s.name != "test_bronze" for s in stages)

    def test_full_flag_propagates_to_bronze_load(self) -> None:
        stages = build_stages(_ns(full=True))
        bronze = next(s for s in stages if s.name == "bronze_load")
        assert "--full-refresh" in bronze.uv_args

    def test_full_flag_propagates_to_build_silver_gold(self) -> None:
        stages = build_stages(_ns(full=True))
        build = next(s for s in stages if s.name == "build_silver_gold")
        assert "--full-refresh" in build.uv_args

    def test_dry_run_propagates_to_bronze_load(self) -> None:
        stages = build_stages(_ns(dry_run=True))
        bronze = next(s for s in stages if s.name == "bronze_load")
        assert "--dry-run" in bronze.uv_args

    def test_dry_run_does_not_propagate_to_dbt_runner(self) -> None:
        stages = build_stages(_ns(dry_run=True))
        build = next(s for s in stages if s.name == "build_silver_gold")
        assert "--dry-run" not in build.uv_args

    def test_no_stages_returns_just_bronze_load(self) -> None:
        # `bronze_load` is unconditional -- it always runs even when the user
        # passes --layers silver. Pin that invariant so a future refactor
        # can't silently drop it.
        stages = build_stages(_ns(layers=[]))
        assert [s.name for s in stages] == ["bronze_load"]

    def test_all_stage_commands_use_scripts_python_path(self) -> None:
        # The whole point of the layout refactor -- enforce the path here.
        stages = build_stages(_ns())
        for stage in stages:
            # Every uv_args list is `["run", "<script>"]` with the script
            # under scripts/python/.
            assert len(stage.uv_args) >= 2
            assert stage.uv_args[0] == "run"
            script = stage.uv_args[1]
            assert script.startswith("scripts/python/"), script
            assert Path(script).name in {
                "incremental.py",
                "dbt_runner.py",
                "run_sql_tests.py",
            }


class TestStageDataclass:
    def test_stage_holds_name_and_uv_args(self) -> None:
        s = Stage(name="bronze_load", uv_args=["run", "scripts/python/incremental.py"])
        assert s.name == "bronze_load"
        assert s.uv_args == ["run", "scripts/python/incremental.py"]
        # skip_with defaults to an empty tuple -- not part of the public contract
        # yet, but must be present so the field can be expanded later without
        # breaking constructor callers.
        assert s.skip_with == ()
