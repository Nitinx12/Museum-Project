# CLAUDE.md - Museum ETL Project

## Project Overview
Medallion-architecture data platform mirroring MongoDB to PostgreSQL.
- **Bronze:** Raw mirror (PySpark)
- **Silver/Gold:** Cleaned and modeled (dbt)
- **Quality:** Independent SQL assertions

## Development Commands
### Environment Setup
- `bash scripts/bash/setup_env.sh` - Setup local environment
- `bash scripts/bash/check_dependencies.sh` - Verify requirements

### Pipeline Execution
- `uv run scripts/python/incremental.py` - Load MongoDB to Bronze
- `uv run scripts/python/dbt_runner.py` - Run Silver/Gold dbt models
- `uv run scripts/python/run_sql_tests.py` - Run SQL data quality checks

### Docker
- `docker compose -f docker/compose.yml build` - Build image
- `docker compose -f docker/compose.yml up -d` - Start infrastructure

### Testing
- `pytest` - Run unit tests in `tests/unit`

## Coding Standards
- **Python:** Follow PEP 8. Use `uv` for dependency management. Use `rich` for CLI output.
- **SQL:** Use double quotes for identifiers in PostgreSQL. Follow medallion naming: `dim_` and `fct_` for Gold.
- **dbt:** Models must be tagged `silver` or `gold` to be picked up by `dbt_runner.py`.
- **Tests:** SQL tests in `tests/<layer>/` must use `RAISE EXCEPTION` on failure.

## Architecture Notes
- **Bronze:** `scripts/python/incremental.py` $\rightarrow$ `bronze.*` schema.
- **Silver/Gold:** `museum_dbt/` $\rightarrow$ `silver.*` / `gold.*` schemas.
- **Control:** `bronze.etl_watermarks` and `bronze.etl_logs` track state.
