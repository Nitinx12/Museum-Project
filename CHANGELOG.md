# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `utils/logging_config.py` — industry-standard logging with `logging.config.dictConfig`, rotating JSON file handler, per-run correlation IDs (`run_id`), ECS-compatible JSON fields, and env-var configuration (`LOG_LEVEL`, `LOG_DIR`, `LOG_FORMAT`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`)
- `utils/logger.py` — backwards-compatibility shim that re-exports from `utils.logging_config` and emits a `DeprecationWarning` on first import

### Changed
- **Directory layout** — all Python pipeline scripts moved from `scripts/` into `scripts/python/`:
  - `scripts/incremental.py` → `scripts/python/incremental.py`
  - `scripts/dbt_runner.py` → `scripts/python/dbt_runner.py`
  - `scripts/run_sql_tests.py` → `scripts/python/run_sql_tests.py`
- **main.py location** — moved from `scripts/python/main.py` to project root (`main.py`)
- **`incremental.py` logging** — updated to import `get_logger` from `utils.logging_config`; logger named `museum.extraction.bronze`
- **`dbt_runner.py`** — `log_dir` now resolves to `scripts/../logs` (was `scripts/logs/`)
- All runners and docs updated to use new `scripts/python/` paths:
  - `airflow/dags/museum_pipeline.py`
  - `scripts/ps1/pipeline_runner.ps1`
  - `scripts/bash/run_pipeline.sh`
  - `scripts/bash/check_jars.sh` (comment blocks)
- All documentation updated:
  - `docs/Pipeline.md` — Mermaid diagram and stage reference table
  - `docs/scripts.md` — all three usage blocks
  - `docs/ARCHITECTURE.md` — workload table
  - `README.md` — project structure tree
  - `AGENTS.md` — project-at-a-glance diagram, runner table, examples, verification table, pointers table
