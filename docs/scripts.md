# Scripts Guide

This project uses a mix of Python, Bash, and JavaScript to manage the ETL lifecycle.

## 🚀 Core Pipeline (Python)
These scripts handle the heavy lifting of data movement and transformation.

- **`main.py`**: The top-level entry point. Sequences the entire pipeline (Bronze $\rightarrow$ Silver $\rightarrow$ Gold) and manages logging.
- **`scripts/python/incremental.py`**: Moves data from MongoDB to Postgres (Bronze). Handles auto-discovery, incremental watermarking, and UPSERTs.
- **`scripts/python/dbt_runner.py`**: Orchestrates dbt runs. Ensures Silver is built and tested before Gold begins.
- **`scripts/python/run_sql_tests.py`**: Executes hand-written SQL assertions in `tests/` to verify data integrity across all layers.

## 🛠️ Infrastructure & Environment (Bash)
Helpers for setup, validation, and maintenance.

- **`scripts/bash/setup_env.sh`**: Loads `.env` variables and exports them for the current session.
- **`scripts/bash/check_dependencies.sh`**: Verifies required tools (uv, docker, etc.) and JDBC jars are present.
- **`scripts/bash/check_jars.sh`**: Validates that the Spark/Mongo jars are compatible with the current environment.
- **`scripts/bash/run_pipeline.sh`**: A shell wrapper to trigger the full ETL pipeline.
- **`scripts/bash/monitor_logs.sh`**: Summarizes the `logs/` directory and provides interactive cleanup.
- **`scripts/bash/clean_logs.sh`**: Deletes old log files to save disk space.
- **`scripts/bash/docker_status.sh`**: Quickly checks the health of the Airflow and Postgres containers.

## ⚙️ Automation & Other
- **`scripts/ps1/pipeline_runner.ps1`**: A PowerShell implementation of the pipeline runner for Windows environments.
- **`scripts/JavaScripts/monitor.js`**: A real-time watcher that monitors file changes and triggers updates.
