"""
scripts/python/incremental.py
=============================
Production-grade MongoDB -> PostgreSQL (bronze schema) loader, built on
PySpark. Rebuilt in the style of scripts/extract.py (see that file for the
original reference), wired to this project's actual utils/ package and to
the Spark jar setup already confirmed working in this environment
(PySpark 4.x + mongo-spark-connector_2.13:11.1.0, local jars only).

WHAT IT DOES
------------
1. Auto-discovers every user collection in the configured Mongo database
   (no hardcoded collection list) unless --tables restricts it.
2. For each collection, loads it into Spark via the MongoDB Spark Connector
   and merges it into a same-named table in BRONZE_SCHEMA via the JDBC
   driver in jars/postgresql.jar.
3. Incremental watermark column is auto-detected per collection, checked in
   this priority order:
       updated_at -> updated_timestamp -> created_at -> created_timestamp
   The first one actually present on the collection's documents is used.
   "updated_*" is preferred over "created_*" so that documents modified
   after insert (e.g. a status flip) get re-synced, not just brand-new rows.
   If a collection has neither, it always does a full reload.
4. Rows are UPSERTED, not blindly appended: each document's Mongo `_id`
   is the merge key. The incremental batch lands in a scratch staging
   table, then a single `INSERT ... ON CONFLICT ("_id") DO UPDATE` merges
   it into the real table, using `xmax = 0` to split the result into exact
   inserted-vs-updated counts (no separate Spark-side join needed).
5. Watermark state lives in `<schema>.etl_watermarks` (one row per
   collection). Per-collection run history lives in `<schema>.etl_logs`
   (one audit row per collection per run) -- both plain Postgres tables,
   queryable with any SQL client, in the same schema as the mirrored data.
6. Column names/types are left exactly as Spark infers them from Mongo.
   The one unavoidable exception: Mongo's `_id` (ObjectId) and any nested
   struct/array/map fields aren't representable as native Postgres scalar
   columns over plain JDBC, so they're serialized to a string/JSON string.
7. After each write, a post-load validation step re-counts the target
   table and confirms it matches what was expected -- PASS/FAIL per table.
8. Prints a Rich report at the end: per-collection row counts, inserted /
   updated / skipped, validation result, current watermark state, and a
   run summary -- plus full detail in the daily log file and in
   `<schema>.etl_logs`.

USAGE
-----
    uv run scripts/python/incremental.py                     # every collection in the DB
    uv run scripts/python/incremental.py --tables orders,customers
    uv run scripts/python/incremental.py --full-refresh       # applies to every selected collection
    uv run scripts/python/incremental.py --dry-run            # discover/count only, write nothing
    uv run scripts/python/incremental.py --watermark-column updated_at

Requires (uv add): pyspark pymongo sqlalchemy psycopg2-binary rich python-dotenv
Requires jars/ to already hold the matching mongo-spark-connector + mongo
driver + postgresql jars for your installed PySpark major version -- see
JARS_DIR / _local_jars() below. No network access needed at runtime.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import traceback
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich import box
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

console = Console()


def _rich_showwarning(message, category, filename, lineno, file=None, line=None):
    """Route Python's stdlib `warnings` (e.g. anything utils/engine.py raises
    for an unset optional env var) through Rich instead of the default raw
    two-line stderr dump, so every line this script prints goes through the
    same console."""
    console.print(f"[yellow]⚠ {category.__name__}:[/yellow] {message}")


warnings.showwarning = _rich_showwarning

# ---------------------------------------------------------------------------
# Make `utils` importable regardless of the CWD this script is launched from.
# This file lives at <project_root>/scripts/python/incremental.py, so the
# project root is three levels up.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pyspark
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, MapType, StructType, TimestampType
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from utils.logging_config import get_logger

log = get_logger("museum.extraction.bronze")


def _mongo_db() -> str:
    from utils.connection import MONGO_DB  # noqa: E402
    return MONGO_DB


def _mongo_client():
    from utils.engine import mongo_client  # noqa: E402
    return mongo_client()


def _postgres_engine():
    from utils.engine import postgres_engine  # noqa: E402
    return postgres_engine()

# System / internal collections we never want to mirror into Postgres.
MONGO_SYSTEM_PREFIXES = ("system.",)

BRONZE_SCHEMA = "bronze"
PRIMARY_KEY_COLUMN = "_id"

# Checked in this order per collection; first one actually present wins.
# "updated_*" is preferred over "created_*" because it also catches rows
# that were modified after insert, not just brand-new ones.
INCREMENTAL_COLUMN_CANDIDATES = [
    "updated_at",
    "updated_timestamp",
    "created_at",
    "created_timestamp",
]

WATERMARK_TABLE = "etl_watermarks"
LOG_TABLE = "etl_logs"

JARS_DIR = PROJECT_ROOT / "jars"
LOG_DIR_NAME = "logs"


# ---------------------------------------------------------------------------
# Spark bootstrap
# ---------------------------------------------------------------------------
def _local_jars() -> list[str]:
    jars = []
    if JARS_DIR.is_dir():
        jars.extend(str(p) for p in JARS_DIR.iterdir() if p.suffix == ".jar")
    return jars


def build_spark(app_name: str) -> SparkSession:
    from utils.connection import MONGO_URI  # noqa: E402
    jars = _local_jars()
    builder = (
        pyspark.sql.SparkSession.builder.appName(app_name)
        .config("spark.mongodb.read.connection.uri", MONGO_URI)
        .config("spark.mongodb.write.connection.uri", MONGO_URI)
    )
    if jars:
        builder = builder.config("spark.jars", ",".join(jars))
    spark = builder.getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark


# ---------------------------------------------------------------------------
# Postgres helpers
# ---------------------------------------------------------------------------
def postgres_jdbc_url_and_props() -> tuple[str, dict[str, str]]:
    url = (
        f"jdbc:postgresql://{os.environ['POSTGRES_HOST']}:"
        f"{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
    )
    props = {
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
        "driver": "org.postgresql.Driver",
    }
    return url, props


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{BRONZE_SCHEMA}"'))


def ensure_control_tables(engine: Engine) -> None:
    ensure_schema(engine)
    watermarks_ddl = f"""
        CREATE TABLE IF NOT EXISTS "{BRONZE_SCHEMA}"."{WATERMARK_TABLE}" (
            table_name         TEXT PRIMARY KEY,
            incremental_column TEXT,
            last_watermark_value TIMESTAMPTZ,
            last_run_at          TIMESTAMPTZ,
            last_run_mode        TEXT,
            last_run_rows_inserted BIGINT DEFAULT 0,
            last_run_rows_updated BIGINT DEFAULT 0
        )
    """
    logs_ddl = f"""
        CREATE TABLE IF NOT EXISTS "{BRONZE_SCHEMA}"."{LOG_TABLE}" (
            id               BIGSERIAL PRIMARY KEY,
            run_id           TEXT NOT NULL,
            started_at       TIMESTAMPTZ NOT NULL,
            finished_at      TIMESTAMPTZ NOT NULL,
            table_name       TEXT NOT NULL,
            mode             TEXT,
            watermark_before TIMESTAMPTZ,
            watermark_after  TIMESTAMPTZ,
            mongo_rows       BIGINT,
            rows_inserted    BIGINT,
            rows_updated     BIGINT,
            batch_rows       BIGINT,
            skipped_rows     BIGINT,
            columns          INTEGER,
            status           TEXT,
            validation_status TEXT,
            validation_detail TEXT,
            error            TEXT,
            error_full       TEXT,
            complex_fields_flattened TEXT[]
        )
    """
    with engine.begin() as conn:
        conn.execute(text(watermarks_ddl))
        conn.execute(text(logs_ddl))
        _migrate_etl_logs_columns(conn)


def _migrate_etl_logs_columns(conn) -> None:
    # CREATE TABLE IF NOT EXISTS is a no-op when the table already exists, so
    # an older deployment (with a different etl_logs shape) keeps the old
    # columns and every insert blows up with "column ... does not exist".
    # We add any missing columns the current code expects, idempotently.
    expected: dict[str, str] = {
        "watermark_before": "TIMESTAMPTZ",
        "watermark_after": "TIMESTAMPTZ",
        "mongo_rows": "BIGINT",
        "rows_inserted": "BIGINT",
        "rows_updated": "BIGINT",
        "batch_rows": "BIGINT",
        "skipped_rows": "BIGINT",
        "columns": "INTEGER",
        "validation_status": "TEXT",
        "validation_detail": "TEXT",
        "error": "TEXT",
        "error_full": "TEXT",
        "complex_fields_flattened": "TEXT[]",
    }
    for col, typ in expected.items():
        conn.execute(
            text(
                f'ALTER TABLE "{BRONZE_SCHEMA}"."{LOG_TABLE}" '
                f'ADD COLUMN IF NOT EXISTS "{col}" {typ}'
            )
        )


def table_exists(engine: Engine, table: str) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text(f"""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = :schema
                      AND table_name   = :table
                )
            """),
            {"schema": BRONZE_SCHEMA, "table": table},
        )
        return result.scalar()  # type: ignore[return-value]


def get_row_count(engine: Engine, table: str) -> int:
    with engine.begin() as conn:
        result = conn.execute(
            text(f'SELECT count(*) FROM "{BRONZE_SCHEMA}"."{table}"'),
        )
        return int(result.scalar() or 0)  # type: ignore[arg-type]


def get_watermark(engine: Engine, table: str) -> Optional[datetime]:
    with engine.begin() as conn:
        result = conn.execute(
            text(f"""
                SELECT last_watermark_value
                FROM "{BRONZE_SCHEMA}"."{WATERMARK_TABLE}"
                WHERE table_name = :table
            """),
            {"table": table},
        )
        row = result.fetchone()
        return row[0] if row else None  # type: ignore[return-value]


def upsert_watermark(
    engine: Engine,
    table: str,
    column: Optional[str],
    value: Optional[datetime],
    mode: str,
    rows_inserted: int,
    rows_updated: int,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(f"""
                INSERT INTO "{BRONZE_SCHEMA}"."{WATERMARK_TABLE}"
                    (table_name, incremental_column, last_watermark_value,
                     last_run_at, last_run_mode,
                     last_run_rows_inserted, last_run_rows_updated)
                VALUES
                    (:table, :column, :value, :now, :mode, :ins, :upd)
                ON CONFLICT (table_name) DO UPDATE SET
                    incremental_column     = EXCLUDED.incremental_column,
                    last_watermark_value   = EXCLUDED.last_watermark_value,
                    last_run_at            = EXCLUDED.last_run_at,
                    last_run_mode          = EXCLUDED.last_run_mode,
                    last_run_rows_inserted  = EXCLUDED.last_run_rows_inserted,
                    last_run_rows_updated  = EXCLUDED.last_run_rows_updated
            """),
            {
                "table": table,
                "column": column,
                "value": value,
                "now": datetime.now(timezone.utc),
                "mode": mode,
                "ins": rows_inserted,
                "upd": rows_updated,
            },
        )


def fetch_watermark_state(engine: Engine) -> list[dict]:
    with engine.begin() as conn:
        result = conn.execute(
            text(f"""
                SELECT table_name, incremental_column, last_watermark_value,
                       last_run_at, last_run_mode,
                       last_run_rows_inserted, last_run_rows_updated
                FROM "{BRONZE_SCHEMA}"."{WATERMARK_TABLE}"
                ORDER BY table_name
            """),
        )
        cols = ["table_name", "incremental_column", "last_watermark_value",
                "last_run_at", "last_run_mode",
                "last_run_rows_inserted", "last_run_rows_updated"]
        return [dict(zip(cols, row)) for row in result.fetchall()]


def insert_log(
    engine: Engine,
    run_id: str,
    started_at: datetime,
    finished_at: datetime,
    result: "CollectionResult",
) -> None:
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"""
                    INSERT INTO "{BRONZE_SCHEMA}"."{LOG_TABLE}"
                        (run_id, started_at, finished_at, table_name,
                         mode, watermark_before, watermark_after,
                         mongo_rows, rows_inserted, rows_updated,
                         batch_rows, skipped_rows, columns,
                         status, validation_status, validation_detail,
                         error, error_full, complex_fields_flattened)
                    VALUES
                        (:run_id, :started_at, :finished_at, :table_name,
                         :mode, :watermark_before, :watermark_after,
                         :mongo_rows, :rows_inserted, :rows_updated,
                         :batch_rows, :skipped_rows, :columns,
                         :status, :validation_status, :validation_detail,
                         :error, :error_full, :complex_fields)
                """),
                {
                    "run_id": run_id,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "table_name": result.name,
                    "mode": result.mode,
                    "watermark_before": result.watermark_before,
                    "watermark_after": result.watermark_after,
                    "mongo_rows": result.mongo_rows,
                    "rows_inserted": result.rows_inserted,
                    "rows_updated": result.rows_updated,
                    "batch_rows": result.batch_rows,
                    "skipped_rows": result.skipped_rows,
                    "columns": result.columns,
                    "status": result.status,
                    "validation_status": result.validation_status,
                    "validation_detail": result.validation_detail,
                    "error": result.error,
                    "error_full": result.error_full,
                    "complex_fields": result.complex_fields_flattened,
                },
            )
    except SQLAlchemyError:
        log.exception(f"[{result.name}] failed to write audit row to {BRONZE_SCHEMA}.{LOG_TABLE} (non-fatal)")


def validate_collection(engine: Engine, table: str, expected_after: int) -> tuple[str, str]:
    """Post-load validation: re-count the table fresh and compare against
    what we expect it to hold, independent of whatever the write/merge
    step itself reported."""
    actual = get_row_count(engine, table)
    if actual == expected_after:
        return "PASS", f"{actual:,} rows confirmed in Postgres"
    return "FAIL", f"expected {expected_after:,}, found {actual:,} in Postgres"


# ---------------------------------------------------------------------------
# Mongo read
# ---------------------------------------------------------------------------
def read_collection(
    spark: SparkSession, collection: str, incremental_column: Optional[str], since: Optional[datetime]
) -> DataFrame:
    df = (
        spark.read.format("mongodb")
        .option("database", _mongo_db())
        .option("collection", collection)
        .load()
    )
    # Cast explicitly to TimestampType before comparing/filtering, rather
    # than relying on Spark's implicit coercion -- works the same whether
    # Mongo stores the field as a real BSON date or an ISO string, without
    # having to know the exact on-disk representation up front.
    if incremental_column and incremental_column in df.columns:
        df = df.withColumn(incremental_column, F.col(incremental_column).cast(TimestampType()))
        if since is not None:
            df = df.filter(F.col(incremental_column) > F.lit(since))
    return df


def sanitize_for_postgres(df: DataFrame, log_flattened: list) -> DataFrame:
    """
    Make the frame writable via plain JDBC without touching any column's
    *logical* meaning. Only two adjustments are made, both unavoidable:
      - `_id` (BSON ObjectId or plain string) -> string (also our merge key)
      - nested struct/array/map columns -> JSON string (Postgres has no
        native equivalent over plain JDBC)
    Every other column keeps whatever type Spark inferred from Mongo.
    """
    out = df
    if PRIMARY_KEY_COLUMN in out.columns:
        id_type = out.schema[PRIMARY_KEY_COLUMN].dataType
        if isinstance(id_type, StructType) and "oid" in id_type.fieldNames():
            out = out.withColumn(PRIMARY_KEY_COLUMN, F.col(f"{PRIMARY_KEY_COLUMN}.oid"))
        else:
            out = out.withColumn(PRIMARY_KEY_COLUMN, F.col(PRIMARY_KEY_COLUMN).cast("string"))

    for fld in out.schema.fields:
        if fld.name == PRIMARY_KEY_COLUMN:
            continue
        if isinstance(fld.dataType, (StructType, ArrayType, MapType)):
            out = out.withColumn(fld.name, F.to_json(F.col(fld.name)))
            log_flattened.append(fld.name)

    return out


# ---------------------------------------------------------------------------
# Write path: direct append for a brand-new table, staging + upsert-merge
# for an existing one.
# ---------------------------------------------------------------------------
def write_direct(df: DataFrame, collection: str) -> None:
    url, props = postgres_jdbc_url_and_props()
    (
        df.write.format("jdbc")
        .option("url", url)
        .option("dbtable", f"{BRONZE_SCHEMA}.{collection}")
        .options(**props)
        .mode("append")
        .save()
    )


def write_staging(df: DataFrame, staging_table: str) -> None:
    url, props = postgres_jdbc_url_and_props()
    (
        df.write.format("jdbc")
        .option("url", url)
        .option("dbtable", f"{BRONZE_SCHEMA}.{staging_table}")
        .options(**props)
        .mode("overwrite")  # scratch table -- drop/recreate fresh every run
        .save()
    )


def merge_staging_into_target(engine: Engine, collection: str, staging_table: str, columns: list[str]) -> tuple[int, int]:
    """INSERT ... ON CONFLICT (_id) DO UPDATE, using xmax=0 to split the
    result into (rows_inserted, rows_updated) counts in a single statement."""
    quoted_cols = ", ".join(f'"{c}"' for c in columns)
    update_cols = [c for c in columns if c != PRIMARY_KEY_COLUMN]
    set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

    merge_sql = f"""
        WITH upsert AS (
            INSERT INTO "{BRONZE_SCHEMA}"."{collection}" ({quoted_cols})
            SELECT {quoted_cols} FROM "{BRONZE_SCHEMA}"."{staging_table}"
            ON CONFLICT ("{PRIMARY_KEY_COLUMN}") DO UPDATE SET {set_clause}
            RETURNING (xmax = 0) AS inserted
        )
        SELECT
            count(*) FILTER (WHERE inserted)     AS rows_inserted,
            count(*) FILTER (WHERE NOT inserted) AS rows_updated
        FROM upsert
    """
    with engine.begin() as conn:
        row = conn.execute(text(merge_sql)).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def drop_table(engine: Engine, table: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{BRONZE_SCHEMA}"."{table}"'))


# ---------------------------------------------------------------------------
# Per-collection pipeline
# ---------------------------------------------------------------------------
@dataclass
class CollectionResult:
    name: str
    status: str = "PENDING"
    mode: str = ""
    mongo_rows: int = 0
    postgres_rows_before: int = 0
    postgres_rows_after: int = 0
    batch_rows: int = 0
    skipped_rows: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    columns: int = 0
    incremental_column: Optional[str] = None
    watermark_before: Optional[datetime] = None
    watermark_after: Optional[datetime] = None
    validation_status: str = "N/A"
    validation_detail: str = ""
    complex_fields_flattened: list[str] = field(default_factory=list)
    error: str = ""
    error_full: str = ""
    seconds: float = 0.0


def short_error(exc: BaseException) -> str:
    msg = str(exc)
    if len(msg) > 200:
        msg = msg[:200].rstrip() + " ..."
    return msg


def discover_collections(mongo_db) -> list[str]:
    return sorted(
        c for c in mongo_db.list_collection_names()
        if not any(c.startswith(p) for p in MONGO_SYSTEM_PREFIXES)
    )


def detect_incremental_column(sample_fields: list[str], override: Optional[str]) -> Optional[str]:
    if override:
        return override if override in sample_fields else None
    for col in INCREMENTAL_COLUMN_CANDIDATES:
        if col in sample_fields:
            return col
    return None


def ensure_unique_id_index(engine: Engine, collection: str) -> bool:
    index_name = f"idx_{collection}_id"
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS "{index_name}"
                    ON "{BRONZE_SCHEMA}"."{collection}" ("{PRIMARY_KEY_COLUMN}")
                """)
            )
        return True
    except SQLAlchemyError as exc:
        log.warning(
            f"[{collection}] unique index on {PRIMARY_KEY_COLUMN} could not be "
            f"created ({exc}). Merge may produce duplicate-key errors -- "
            f"falling back to append-only for this collection."
        )
        return False


def process_collection(
    spark: SparkSession,
    mongo_db,
    engine: Engine,
    collection: str,
    full_refresh: bool,
    dry_run: bool,
    run_id: str,
    watermark_column_override: Optional[str],
) -> CollectionResult:
    start = time.time()
    started_at = datetime.now(timezone.utc)
    result = CollectionResult(name=collection)

    try:
        mongo_total = mongo_db[collection].estimated_document_count()
        result.mongo_rows = mongo_total

        pg_before = get_row_count(engine, collection)
        result.postgres_rows_before = pg_before

        sample = mongo_db[collection].find_one()
        sample_fields = list(sample.keys()) if sample else []
        incremental_column = detect_incremental_column(sample_fields, watermark_column_override)
        result.incremental_column = incremental_column

        if full_refresh:
            since = None
        elif incremental_column:
            since = get_watermark(engine, collection)
        else:
            since = None
            log.warning(
                f"[{collection}] no incremental column found among {INCREMENTAL_COLUMN_CANDIDATES}; "
                f"every run will fully reload this collection."
            )
        result.watermark_before = since
        result.mode = "full" if since is None else "incremental"

        if full_refresh and table_exists(engine, collection):
            log.info(f"[{collection}] --full-refresh: truncating table before reload")
            if not dry_run:
                with engine.begin() as conn:
                    conn.execute(text(f'TRUNCATE TABLE "{BRONZE_SCHEMA}"."{collection}"'))
                pg_before = 0
                result.postgres_rows_before = 0

        df = read_collection(spark, collection, incremental_column, since)
        df = sanitize_for_postgres(df, result.complex_fields_flattened)
        result.columns = len(df.columns)

        batch_rows = df.count()
        result.batch_rows = batch_rows
        result.skipped_rows = max(mongo_total - batch_rows, 0)

        new_watermark = since
        if batch_rows > 0 and incremental_column and incremental_column in df.columns:
            new_watermark = df.agg(F.max(incremental_column)).collect()[0][0] or since
        result.watermark_after = new_watermark

        if batch_rows == 0:
            result.status = "SKIPPED (no new/changed rows)"
            result.postgres_rows_after = pg_before
            result.validation_status, result.validation_detail = validate_collection(engine, collection, pg_before)
            if not dry_run:
                upsert_watermark(engine, collection, incremental_column, new_watermark, result.mode, 0, 0)
            log.info(f"[{collection}] nothing new to load (mode={result.mode})")
            return result

        if dry_run:
            result.status = "DRY-RUN"
            result.postgres_rows_after = pg_before
            log.info(f"[{collection}] dry-run: would merge {batch_rows} row(s)")
            return result

        target_exists = table_exists(engine, collection)
        can_merge = PRIMARY_KEY_COLUMN in df.columns

        if not target_exists:
            log.info(f"[{collection}] first load: creating table and inserting {batch_rows} row(s)")
            ensure_schema(engine)
            write_direct(df, collection)
            result.rows_inserted, result.rows_updated = batch_rows, 0
            ensure_unique_id_index(engine, collection)
        elif not can_merge:
            log.warning(f'[{collection}] no "{PRIMARY_KEY_COLUMN}" column present -- appending instead of upserting')
            write_direct(df, collection)
            result.rows_inserted, result.rows_updated = batch_rows, 0
        else:
            merge_ready = ensure_unique_id_index(engine, collection)
            if not merge_ready:
                log.warning(f"[{collection}] falling back to append-only for this run")
                write_direct(df, collection)
                result.rows_inserted, result.rows_updated = batch_rows, 0
            else:
                staging_table = f"_stg_{collection}"
                log.info(f"[{collection}] merging {batch_rows} row(s) via staging table {staging_table}")
                write_staging(df, staging_table)
                try:
                    result.rows_inserted, result.rows_updated = merge_staging_into_target(
                        engine, collection, staging_table, df.columns
                    )
                finally:
                    drop_table(engine, staging_table)

        expected_after = pg_before + result.rows_inserted
        result.postgres_rows_after = get_row_count(engine, collection)
        result.validation_status, result.validation_detail = validate_collection(engine, collection, expected_after)

        if result.validation_status == "PASS":
            upsert_watermark(
                engine, collection, incremental_column, new_watermark, result.mode,
                result.rows_inserted, result.rows_updated,
            )
            result.status = "OK"
        else:
            result.status = "VALIDATION FAILED"
            log.error(f"[{collection}] post-load validation FAILED: {result.validation_detail}")

    except Exception as exc:  # noqa: BLE001 - keep going for other collections
        result.status = "FAILED"
        result.error = short_error(exc)
        result.error_full = traceback.format_exc()
        log.error(f"[{collection}] extraction failed: {result.error}")
    finally:
        result.seconds = time.time() - start
        finished_at = datetime.now(timezone.utc)
        insert_log(engine, run_id, started_at, finished_at, result)

    return result


# ---------------------------------------------------------------------------
# Rich reporting
# ---------------------------------------------------------------------------
def render_report(results: list[CollectionResult], elapsed: float, dry_run: bool, run_id: str, engine: Optional[Engine] = None) -> None:
    console.print()
    console.print(
        Panel.fit(
            "[bold]MongoDB -> PostgreSQL Incremental Load Report[/bold]\n"
            f"Database: [cyan]{_mongo_db()}[/cyan]  ->  Schema: [cyan]{BRONZE_SCHEMA}[/cyan]\n"
            f"Run ID: [magenta]{run_id}[/magenta]\n"
            f"Run finished: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
            + ("  [yellow](DRY RUN - no data written)[/yellow]" if dry_run else ""),
            border_style="cyan",
        )
    )

    table = Table(title="Per-Collection Detail", box=box.SIMPLE_HEAVY, show_lines=False)
    table.add_column("Table", style="bold")
    table.add_column("Mode")
    table.add_column("Watermark Col")
    table.add_column("Mongo Rows", justify="right")
    table.add_column("PG Rows (Before)", justify="right")
    table.add_column("Inserted", justify="right", style="green")
    table.add_column("Updated", justify="right", style="cyan")
    table.add_column("Skipped", justify="right", style="yellow")
    table.add_column("PG Rows (After)", justify="right")
    table.add_column("Columns", justify="right")
    table.add_column("Time (s)", justify="right")
    table.add_column("Status")
    table.add_column("Validation")

    for r in results:
        status_style = {"OK": "green", "DRY-RUN": "cyan"}.get(r.status, "yellow" if "SKIPPED" in r.status else "red")
        validation_style = {"PASS": "green", "N/A": "dim"}.get(r.validation_status, "red")
        table.add_row(
            r.name, r.mode, r.incremental_column or "-",
            f"{r.mongo_rows:,}", f"{r.postgres_rows_before:,}",
            f"{r.rows_inserted:,}", f"{r.rows_updated:,}", f"{r.skipped_rows:,}",
            f"{r.postgres_rows_after:,}", str(r.columns), f"{r.seconds:.2f}",
            f"[{status_style}]{r.status}[/{status_style}]",
            f"[{validation_style}]{r.validation_status}[/{validation_style}]",
        )
    console.print(table)

    validation_issues = [r for r in results if r.validation_status == "FAIL"]
    if validation_issues:
        vtable = Table(title="Post-Load Validation Detail", box=box.MINIMAL, style="red")
        vtable.add_column("Table")
        vtable.add_column("Detail")
        for r in validation_issues:
            vtable.add_row(r.name, r.validation_detail)
        console.print(vtable)

    if engine is not None:
        try:
            state = fetch_watermark_state(engine)
        except SQLAlchemyError:
            state = []
        if state:
            wtable = Table(title=f"Watermark State ({BRONZE_SCHEMA}.{WATERMARK_TABLE})", box=box.MINIMAL_DOUBLE_HEAD)
            wtable.add_column("Table")
            wtable.add_column("Watermark Col")
            wtable.add_column("Last Value Loaded")
            wtable.add_column("Last Run At")
            wtable.add_column("Last Mode")
            wtable.add_column("Ins", justify="right")
            wtable.add_column("Upd", justify="right")
            for row in state:
                wtable.add_row(
                    row["table_name"], row["incremental_column"] or "-",
                    str(row["last_watermark_value"]) if row["last_watermark_value"] else "-",
                    str(row["last_run_at"]), row["last_run_mode"] or "-",
                    f"{row['last_run_rows_inserted']:,}", f"{row['last_run_rows_updated']:,}",
                )
            console.print(wtable)
        console.print(
            f"[dim]Full per-collection audit trail for every run is stored in "
            f"{BRONZE_SCHEMA}.{LOG_TABLE} (run_id = {run_id}).[/dim]"
        )

    flattened = {r.name: r.complex_fields_flattened for r in results if r.complex_fields_flattened}
    if flattened:
        note = Table(title="Nested Fields Serialized to JSON (unavoidable for JDBC)", box=box.MINIMAL)
        note.add_column("Table")
        note.add_column("Fields")
        for name, fields_ in flattened.items():
            note.add_row(name, ", ".join(fields_))
        console.print(note)

    failed = [r for r in results if r.status == "FAILED"]
    if failed:
        err_table = Table(title="Failures", box=box.MINIMAL, style="red")
        err_table.add_column("Table", no_wrap=True)
        err_table.add_column("Error", overflow="fold", max_width=90)
        for r in failed:
            err_table.add_row(r.name, r.error or "unknown error")
        console.print(err_table)

    total_mongo = sum(r.mongo_rows for r in results)
    total_inserted = sum(r.rows_inserted for r in results)
    total_updated = sum(r.rows_updated for r in results)
    total_skipped = sum(r.skipped_rows for r in results)
    total_pg_after = sum(r.postgres_rows_after for r in results)
    n_succeeded = sum(1 for r in results if r.status == "OK")
    n_skipped = sum(1 for r in results if "SKIPPED" in r.status)
    has_issues = bool(failed) or bool(validation_issues)

    outcome = Table(title="Run Outcome", box=box.ROUNDED, title_style="bold", header_style="bold cyan",
                     border_style="red" if has_issues else "green", show_lines=False)
    for col in ("Collections", "Succeeded", "Skipped", "Failed", "Validation Failures", "Run Time"):
        outcome.add_column(col, justify="center")
    outcome.add_row(
        str(len(results)), f"[green]{n_succeeded}[/green]", f"[yellow]{n_skipped}[/yellow]",
        f"[red]{len(failed)}[/red]" if failed else "0",
        f"[red]{len(validation_issues)}[/red]" if validation_issues else "0",
        f"{elapsed:.2f}s",
    )

    totals = Table(title="Row Totals", box=box.ROUNDED, title_style="bold", header_style="bold cyan",
                   border_style="cyan", show_lines=False)
    for col in ("Mongo Rows", "Inserted", "Updated", "Skipped (unchanged)", "Now in Postgres"):
        totals.add_column(col, justify="center")
    totals.add_row(
        f"{total_mongo:,}", f"[green]{total_inserted:,}[/green]", f"[cyan]{total_updated:,}[/cyan]",
        f"[yellow]{total_skipped:,}[/yellow]", f"{total_pg_after:,}",
    )
    console.print(Columns([outcome, totals], padding=(0, 2)))

    console.print(
        Panel(
            f"[bold {'red' if has_issues else 'green'}]"
            f"{'RUN COMPLETED WITH ISSUES' if has_issues else 'RUN COMPLETED SUCCESSFULLY'}"
            f"[/bold {'red' if has_issues else 'green'}]",
            border_style="red" if has_issues else "green",
        )
    )


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incremental MongoDB -> PostgreSQL bronze loader (PySpark).")
    parser.add_argument(
        "--tables", type=str, default=None,
        help="Comma-separated list of collection names to process (default: all discovered collections).",
    )
    parser.add_argument(
        "--full-refresh", action="store_true",
        help="Ignore watermark state and reload every selected collection from scratch "
        "(truncates existing Postgres tables before merging).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Discover, count, and compute what would be loaded -- do not write anything to Postgres.",
    )
    parser.add_argument(
        "--watermark-column", type=str, default=None,
        help="Force a specific column name as the incremental watermark for every collection "
        f"(default: auto-detect per collection from {INCREMENTAL_COLUMN_CANDIDATES}).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    start = time.time()
    run_id = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"

    console.rule("[bold cyan]incremental: MongoDB -> PostgreSQL incremental load[/bold cyan]")
    log.info(f"Starting run {run_id} (full_refresh={args.full_refresh}, dry_run={args.dry_run}, tables={args.tables})")

    mongo_db = _mongo_client()
    engine = _postgres_engine()
    ensure_control_tables(engine)

    if args.tables:
        collections = [t.strip() for t in args.tables.split(",") if t.strip()]
        log.info(f"Restricting run to user-specified collections: {collections}")
    else:
        collections = discover_collections(mongo_db)

    if not collections:
        console.print("[yellow]No collections found to process.[/yellow]")
        engine.dispose()
        return 0

    spark = build_spark("incremental-load")
    results: list[CollectionResult] = []

    try:
        with Progress(
            SpinnerColumn(), TextColumn("[bold blue]{task.fields[coll]}"), BarColumn(),
            TextColumn("{task.completed}/{task.total}"), TimeElapsedColumn(), console=console,
        ) as progress:
            task = progress.add_task("extract", total=len(collections), coll="starting...")
            for coll in collections:
                progress.update(task, coll=coll)
                res = process_collection(
                    spark, mongo_db, engine, coll, args.full_refresh, args.dry_run, run_id, args.watermark_column,
                )
                results.append(res)
                progress.advance(task)
    finally:
        spark.sparkContext.setLogLevel("ERROR")
        spark.stop()

    elapsed = time.time() - start
    render_report(results, elapsed, args.dry_run, run_id, engine)
    engine.dispose()

    log.info(f"Run {run_id} complete in {elapsed:.2f}s")
    return 1 if any(r.status in ("FAILED", "VALIDATION FAILED") for r in results) else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SQLAlchemyError:
        console.print_exception()
        sys.exit(2)
    except Exception:  # noqa: BLE001
        console.print("[bold red]Unhandled error:[/bold red]")
        console.print(traceback.format_exc())
        sys.exit(2)
