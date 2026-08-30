import subprocess
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.models import Variable
from airflow.sdk import task
from airflow.sdk.timezone import datetime

# Time configuration
local_tz = pendulum.timezone("Asia/Kolkata")

# Absolute path to the project root on the Airflow worker, i.e. the folder
# that directly contains scripts/, the dbt project, jars/, logs/, etc.
# Set this once via `airflow variables set MUSEUM_PROJECT_ROOT /path/to/project`
# (or in the UI/Variables) -- the default below is just a placeholder.
PROJECT_ROOT = Variable.get("MUSEUM_PROJECT_ROOT", default_var="/opt/airflow/museum_project")

# Default Arguments
default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def _run(args: list[str]) -> None:
    """Run one of the project's `uv run scripts/...` CLI scripts from the
    project root and raise (failing the Airflow task) if it exits non-zero.
    Each script already streams its own Rich-formatted progress/summary to
    stdout, which lands in the task's Airflow log."""
    result = subprocess.run(args, cwd=PROJECT_ROOT, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {result.returncode}: {' '.join(args)}"
        )


# DAG definition
with DAG(
    dag_id="museum_project",
    description="Museum ETL Pipeline",
    default_args=default_args,
    schedule="0 13 * * MON,WED,FRI",  # 1 PM IST on Mon/Wed/Fri
    start_date=datetime(2024, 1, 1, tzinfo=local_tz),
    catchup=False,
    tags=["etl", "museum", "portfolio"],
) as dag:

    # Bronze: Mongo -> Postgres incremental load
    @task(task_id="bronze_load")
    def bronze_load():
        _run(["uv", "run", "scripts/incremental.py"])

    # Our own SQL tests (tests/bronze/*.sql) against the bronze data just
    # loaded. Fail fast here, before spending time building silver/gold on
    # top of bronze data that's already known to be bad.
    @task(task_id="test_bronze")
    def test_bronze():
        _run(["uv", "run", "scripts/run_sql_tests.py", "--layer", "bronze"])

    # Silver + gold: dbt build only. Tests run as their own task below, kept
    # separate so a build failure and a test failure show up as two
    # distinct, separately retriable/alertable stages instead of one big run.
    @task(task_id="build_silver_gold")
    def build_silver_gold():
        _run(["uv", "run", "scripts/dbt_runner.py", "--skip-tests"])

    # Our own SQL tests (tests/silver/*.sql, tests/gold/*.sql) against the
    # models just built.
    @task(task_id="test_silver_gold")
    def test_silver_gold():
        _run(["uv", "run", "scripts/run_sql_tests.py", "--layer", "silver", "--layer", "gold"])

    # Task Dependencies
    bronze_load_task = bronze_load()
    test_bronze_task = test_bronze()
    build_task = build_silver_gold()
    test_silver_gold_task = test_silver_gold()

    bronze_load_task >> test_bronze_task >> build_task >> test_silver_gold_task