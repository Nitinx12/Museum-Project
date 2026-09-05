# ============================================================================
# Makefile — museum-etl
# ----------------------------------------------------------------------------
# Top-level entry point for the most common project commands. Anything you
# can run with `uv run` or `bash scripts/bash/*` is also available here.
#
# Usage:
#   make help          # show this list
#   make install       # install Python deps with uv
#   make test          # run unit tests
#   make lint          # syntax-check every .py file
#   make pipeline      # run the full ETL pipeline (no tests, no refresh)
#   make pipeline-full # full pipeline + --full-refresh
#   make pipeline-bronze  # bronze load + bronze tests only
#   make pipeline-tests   # load + build, skip the SQL test stages
#   make dry-run       # incremental --dry-run (counts only, no writes)
#   make logs-summary  # report on the logs/ directory
#   make logs-clean    # delete old/large log files (asks for confirmation)
#   make clean         # remove Python bytecode + pytest cache
# ============================================================================

SHELL := /usr/bin/env bash
PY    := uv run python
PIP   := uv

.DEFAULT_GOAL := help

.PHONY: help
help: ## show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: install
install: ## install dependencies with uv
	uv sync --all-extras --dev

.PHONY: test
test: ## run unit tests
	uv run pytest tests/unit

.PHONY: lint
lint: ## syntax-check every Python file
	uv run python -c "import ast, pathlib; [ast.parse(p.read_bytes()) for p in pathlib.Path('.').rglob('*.py')]"

.PHONY: pipeline
pipeline: ## run the full ETL pipeline (load + build + tests, no refresh)
	uv run main.py

.PHONY: pipeline-full
pipeline-full: ## run the full pipeline with --full-refresh
	uv run main.py --full

.PHONY: pipeline-bronze
pipeline-bronze: ## bronze load + bronze tests only
	uv run main.py --bronze-only

.PHONY: pipeline-tests
pipeline-tests: ## load + build, skip both test stages
	uv run main.py --skip-tests

.PHONY: dry-run
dry-run: ## discover + count only, no writes
	uv run scripts/python/incremental.py --dry-run

.PHONY: logs-summary
logs-summary: ## report on the logs/ directory
	bash scripts/bash/monitor_logs.sh summary

.PHONY: logs-clean
logs-clean: ## delete old/large log files (asks for confirmation)
	bash scripts/bash/monitor_logs.sh clean

.PHONY: clean
clean: ## remove Python bytecode + pytest cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache dist build *.egg-info 2>/dev/null || true
