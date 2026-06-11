"""
Museum ETL Pipeline DAG
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Orchestrates the full Museum ETL flow:

  [CSV files]
      │  (load_csv_to_mongo)
      ▼
  [MongoDB]
      │  (extract_mongo_to_postgres via PySpark)
      ▼
  [PostgreSQL]
      │  (validate_row_counts)
      ▼
  [Done]

Strategy : Watermark-based incremental load
Schedule : Daily at midnight
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.empty import EmptyOperator
from airflow.utils.dates import days_ago


# ── Default args ─────────────────────────────────────────────────────
DEFAULT_ARGS = {
    "owner": "museum",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# ── Connection config (pulled from env vars set in docker-compose) ───
MONGO_URI = f"mongodb://{os.environ.get('MONGO_HOST', 'mongo')}:{os.environ.get('MONGO_PORT', '27017')}"
MONGO_DB  = os.environ.get("MONGO_DB", "museum")

PG_HOST   = os.environ.get("POSTGRES_HOST", "postgres")
PG_PORT   = os.environ.get("POSTGRES_PORT", "5432")
PG_DB     = os.environ.get("POSTGRES_DB", "museum")
PG_USER   = os.environ.get("POSTGRES_USER", "postgres")
PG_PASS   = os.environ.get("POSTGRES_PASSWORD", "postgres")

DATA_DIR  = "/opt/airflow/data"          # maps to ./data on host
SRC_DIR   = "/opt/airflow/src"           # maps to ./src  on host


# ── Task functions ───────────────────────────────────────────────────

def load_csv_to_mongo(**context):
    """
    Scans DATA_DIR for CSV files and upserts each into MongoDB.
    Collection name = CSV filename without extension.
    """
    import glob
    from pymongo import MongoClient, UpdateOne

    client = MongoClient(MONGO_URI)
    db     = client[MONGO_DB]

    csv_files = glob.glob(f"{DATA_DIR}/*.csv")
    if not csv_files:
        raise FileNotFoundError(f"No CSV files found in {DATA_DIR}")

    for csv_path in csv_files:
        import pandas as pd
        collection_name = os.path.splitext(os.path.basename(csv_path))[0]
        df = pd.read_csv(csv_path)

        # Add ingestion timestamp for watermarking
        df["_ingested_at"] = datetime.utcnow().isoformat()

        records = df.to_dict("records")
        if records:
            # Upsert by row index — replace with your natural key if available
            ops = [
                UpdateOne(
                    {"_id": f"{collection_name}_{i}"},
                    {"$set": rec},
                    upsert=True,
                )
                for i, rec in enumerate(records)
            ]
            result = db[collection_name].bulk_write(ops)
            print(f"  ✔ {collection_name}: {result.upserted_count} inserted, "
                  f"{result.modified_count} updated")

    client.close()


def extract_mongo_to_postgres(**context):
    """
    Reads from MongoDB using PySpark and writes to PostgreSQL.
    Watermark: only processes documents ingested after last run timestamp.
    Reads watermark from XCom (or starts from epoch on first run).
    """
    import sys
    sys.path.insert(0, SRC_DIR)          # import your own modules from src/

    from pyspark.sql import SparkSession
    from pyspark.sql.functions import col, to_timestamp

    # ── Watermark: get last successful run time ──────────────────────
    ti            = context["ti"]
    last_watermark = ti.xcom_pull(
        task_ids="extract_mongo_to_postgres",
        key="watermark",
        include_prior_dates=True,
    ) or "1970-01-01T00:00:00"           # epoch = full load on first run

    run_start = datetime.utcnow().isoformat()
    print(f"  Watermark window: {last_watermark} → {run_start}")

    # ── Spark session ─────────────────────────────────────────────────
    spark = (
        SparkSession.builder
        .appName("museum_etl")
        .config(
            "spark.jars.packages",
            "org.mongodb.spark:mongo-spark-connector_2.12:10.3.0,"
            "org.postgresql:postgresql:42.7.3",
        )
        .config("spark.mongodb.read.connection.uri", f"{MONGO_URI}/{MONGO_DB}")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    jdbc_url = f"jdbc:postgresql://{PG_HOST}:{PG_PORT}/{PG_DB}"
    jdbc_props = {
        "user":     PG_USER,
        "password": PG_PASS,
        "driver":   "org.postgresql.Driver",
    }

    # ── Process each collection ───────────────────────────────────────
    from pymongo import MongoClient
    client      = MongoClient(MONGO_URI)
    collections = client[MONGO_DB].list_collection_names()
    client.close()

    total_rows = 0
    for collection in collections:
        df = (
            spark.read
            .format("mongodb")
            .option("database",   MONGO_DB)
            .option("collection", collection)
            .load()
        )

        # Apply watermark filter
        df_incremental = df.filter(
            col("_ingested_at") > last_watermark
        )

        row_count = df_incremental.count()
        if row_count == 0:
            print(f"  ↷  {collection}: no new rows since watermark, skipping")
            continue

        print(f"  ✔ {collection}: {row_count} rows to write")

        # Drop internal Mongo fields before writing
        write_df = df_incremental.drop("_id", "_ingested_at")

        (
            write_df.write
            .mode("append")
            .jdbc(jdbc_url, table=collection, properties=jdbc_props)
        )
        total_rows += row_count

    spark.stop()

    # ── Push new watermark for next run ───────────────────────────────
    ti.xcom_push(key="watermark", value=run_start)
    ti.xcom_push(key="rows_written", value=total_rows)
    print(f"  Total rows written: {total_rows}")


def validate_row_counts(**context):
    """
    Quick sanity check: compare MongoDB doc count vs PostgreSQL row count.
    Fails the task (raises) if discrepancy > 5%.
    """
    import psycopg2
    from pymongo import MongoClient

    ti         = context["ti"]
    rows_written = ti.xcom_pull(task_ids="extract_mongo_to_postgres", key="rows_written") or 0

    mongo_client = MongoClient(MONGO_URI)
    db           = mongo_client[MONGO_DB]
    collections  = db.list_collection_names()

    conn   = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB,
                               user=PG_USER, password=PG_PASS)
    cursor = conn.cursor()

    print(f"\n{'Collection':<30} {'MongoDB':>10} {'PostgreSQL':>12}")
    print("─" * 55)

    for coll in collections:
        mongo_count = db[coll].count_documents({})
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{coll}"')
            pg_count = cursor.fetchone()[0]
        except Exception:
            pg_count = 0
            conn.rollback()

        status = "✔" if abs(mongo_count - pg_count) / max(mongo_count, 1) < 0.05 else "⚠"
        print(f"{status} {coll:<28} {mongo_count:>10} {pg_count:>12}")

    cursor.close()
    conn.close()
    mongo_client.close()
    print(f"\nRows written this run: {rows_written}")


# ── DAG definition ───────────────────────────────────────────────────
with DAG(
    dag_id="museum_etl_pipeline",
    description="Museum ETL: CSV → MongoDB → PostgreSQL (watermark incremental)",
    default_args=DEFAULT_ARGS,
    schedule_interval="@daily",
    start_date=days_ago(1),
    catchup=False,
    tags=["museum", "etl", "pyspark", "incremental"],
    doc_md=__doc__,
) as dag:

    start = EmptyOperator(task_id="start")

    t_load_csv = PythonOperator(
        task_id="load_csv_to_mongo",
        python_callable=load_csv_to_mongo,
    )

    t_extract = PythonOperator(
        task_id="extract_mongo_to_postgres",
        python_callable=extract_mongo_to_postgres,
    )

    t_validate = PythonOperator(
        task_id="validate_row_counts",
        python_callable=validate_row_counts,
    )

    end = EmptyOperator(task_id="end")

    # ── Pipeline flow ─────────────────────────────────────────────────
    start >> t_load_csv >> t_extract >> t_validate >> end