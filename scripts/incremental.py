"""
scripts/incremental.py
=======================
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
    uv run scripts/incremental.py                     # every collection in the DB
    uv run scripts/incremental.py --tables orders,customers
    uv run scripts/incremental.py --full-refresh       # applies to every selected collection
    uv run scripts/incremental.py --dry-run            # discover/count only, write nothing
    uv run scripts/incremental.py --watermark-column updated_at

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
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pyspark
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import ArrayType, MapType, StructType, TimestampType
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from utils.connection import MONGO_DB, MONGO_URI
from utils.engine import mongo_client, postgres_engine
from utils.logger import get_logger

log = get_logger("extraction", "incremental")

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

# Control tables (also live in BRONZE_SCHEMA, alongside the mirrored
# collections). Deliberately plain tables so they can be queried with any
# SQL client, not just this script.
WATERMARK_TABLE = "etl_watermarks"
LOG_TABLE = "etl_logs"

# --------------------------------------------------------------------------
# Local jars only -- no spark.jars.packages, no Ivy resolution noise, no
# network access at runtime. Drop the matching jars in <project_root>/jars/.
# Which "matching" means depends on your installed PySpark major version:
#
#   PySpark 4.x (Spark 4.0+, Scala 2.13):
#       mongo-spark-connector_2.13-11.1.0.jar
#       bson-5.1.4.jar, mongodb-driver-core-5.1.x.jar, mongodb-driver-sync-5.1.x.jar
#       postgresql-42.7.4.jar
#
#   PySpark 3.x (Spark 3.2-3.5, Scala 2.12):
#       mongo-spark-connector_2.12-10.4.0.jar
#       bson-5.1.4.jar, mongodb-driver-core-5.1.x.jar, mongodb-driver-sync-5.1.x.jar
#       postgresql-42.7.4.jar
#
# The mongo-spark-connector major version tracks Spark (10.x -> Spark <=3.5,
# 11.x -> Spark 4.0+), and it also switches Scala build (_2.12 -> _2.13) at
# that same boundary. Mixing a 10.x/_2.12 connector jar with a Spark 4.x
# runtime produces java.lang.NoSuchMethodError: ExpressionEncoder.resolveAndBind(...).
JARS_DIR = PROJECT_ROOT / "jars"

CONNECTOR_JAR_URLS = {
    4: {
        "mongo-spark-connector_2.13-11.1.0.jar": "https://repo1.maven.org/maven2/org/mongodb/spark/mongo-spark-connector_2.13/11.1.0/mongo-spark-connector_2.13-11.1.0.jar",
        "mongodb-driver-sync-5.1.4.jar": "https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-sync/5.1.4/mongodb-driver-sync-5.1.4.jar",
        "bson-5.1.4.jar": "https://repo1.maven.org/maven2/org/mongodb/bson/5.1.4/bson-5.1.4.jar",
        "mongodb-driver-core-5.1.4.jar": "https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-core/5.1.4/mongodb-driver-core-5.1.4.jar",
        "bson-record-codec-5.1.4.jar": "https://repo1.maven.org/maven2/org/mongodb/bson-record-codec/5.1.4/bson-record-codec-5.1.4.jar",
    },
    3: {
        "mongo-spark-connector_2.12-10.4.0.jar": "https://repo1.maven.org/maven2/org/mongodb/spark/mongo-spark-connector_2.12/10.4.0/mongo-spark-connector_2.12-10.4.0.jar",
        "mongodb-driver-sync-5.1.4.jar": "https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-sync/5.1.4/mongodb-driver-sync-5.1.4.jar",
        "bson-5.1.4.jar": "https://repo1.maven.org/maven2/org/mongodb/bson/5.1.4/bson-5.1.4.jar",
        "mongodb-driver-core-5.1.4.jar": "https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-core/5.1.4/mongodb-driver-core-5.1.4.jar",
        "bson-record-codec-5.1.4.jar": "https://repo1.maven.org/maven2/org/mongodb/bson-record-codec/5.1.4/bson-record-codec-5.1.4.jar",
    },
}


# ---------------------------------------------------------------------------
# Result bookkeeping
# ---------------------------------------------------------------------------
@dataclass
class CollectionResult:
    name: str
    status: str = "OK"  # OK | SKIPPED | FAILED | VALIDATION FAILED | DRY-RUN
    mode: str = "incremental"  # full | incremental
    incremental_column: Optional[str] = None
    mongo_rows: int = 0
    postgres_rows_before: int = 0
    batch_rows: int = 0  # rows pulled from Mongo this run
    rows_inserted: int = 0
    rows_updated: int = 0
    skipped_rows: int = 0
    postgres_rows_after: int = 0
    columns: int = 0
    error: Optional[str] = None  # short, single-line -- shown in the console table
    error_full: Optional[str] = None  # full traceback -- written to etl_logs only
    seconds: float = 0.0
    complex_fields_flattened: list = field(default_factory=list)
    watermark_before: Optional[datetime] = None
    watermark_after: Optional[datetime] = None
    validation_status: str = "N/A"
    validation_detail: str = ""


# ---------------------------------------------------------------------------
# Error message cleanup
# ---------------------------------------------------------------------------
def short_error(exc: BaseException, max_len: int = 220) -> str:
    """Collapse a possibly huge, multi-line Java/py4j/Python traceback into
    one clean, human-readable line for console display. Full detail is kept
    separately (see CollectionResult.error_full) for the DB audit trail."""
    text_ = str(exc).strip()
    keep: list[str] = []
    for raw in text_.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith(("at ", 'File "')) or re.match(r"^\.{3}\s*\d+\s*more$", ln):
            break
        keep.append(ln)
        if len(keep) >= 2:
            break
    msg = " -- ".join(keep) if keep else (text_.splitlines() or [exc.__class__.__name__])[0]
    msg = re.sub(r"\s+", " ", msg).strip(": ")
    if len(msg) > max_len:
        msg = msg[: max_len - 1].rstrip() + "…"
    return f"{exc.__class__.__name__}: {msg}"


# ---------------------------------------------------------------------------
# Spark session
# ---------------------------------------------------------------------------
def _local_jars() -> list[Path]:
    """Resolve every .jar in JARS_DIR and sanity-check the mongo connector
    build against the installed PySpark major version, so a mismatch fails
    fast with one clear panel instead of the same cryptic
    java.lang.NoSuchMethodError repeated for every collection."""
    jar_paths = sorted(JARS_DIR.glob("*.jar"))
    if not jar_paths:
        console.print(
            Panel.fit(
                f"[bold red]No .jar files found in {JARS_DIR}[/bold red]\n"
                "See the comment above JARS_DIR in this script for the jars you need.",
                border_style="red",
                title="Setup incomplete",
            )
        )
        raise SystemExit(2)

    connector_jars = [p for p in jar_paths if "mongo-spark-connector" in p.name]
    if not connector_jars:
        console.print(
            Panel.fit(
                f"[bold red]No mongo-spark-connector jar found in {JARS_DIR}[/bold red]\n"
                "See the comment above JARS_DIR in this script for the correct one to download.",
                border_style="red",
                title="Setup incomplete",
            )
        )
        raise SystemExit(2)

    connector_name = connector_jars[0].name
    spark_major = int(pyspark.__version__.split(".")[0])
    expected_scala = "_2.13" if spark_major >= 4 else "_2.12"

    if expected_scala not in connector_name:
        wrong_major = 3 if spark_major >= 4 else 4
        tip = "\n".join(
            f"  {name}\n    {url}"
            for name, url in CONNECTOR_JAR_URLS[spark_major].items()
        )
        console.print(
            Panel.fit(
                f"[bold red]Connector/Spark version mismatch[/bold red]\n"
                f"PySpark [yellow]{pyspark.__version__}[/yellow] is installed (needs a "
                f"[cyan]{expected_scala}[/cyan] connector build), but {JARS_DIR} has "
                f"[cyan]{connector_name}[/cyan], which targets Spark {wrong_major}.x.\n"
                "This exact mismatch is what causes NoSuchMethodError: resolveAndBind(...).\n\n"
                f"Delete {connector_name} and download these instead:\n\n{tip}",
                border_style="red",
                title="Version check failed",
            )
        )
        raise SystemExit(2)

    return jar_paths


def build_spark(app_name: str) -> SparkSession:
    jar_paths = _local_jars()
    # extraClassPath (not spark.jars) so the JVM reads the jars in place
    # instead of copying them into a Windows temp dir it can later fail to
    # clean up because it's still holding the file lock.
    classpath = os.pathsep.join(str(p) for p in jar_paths)

    spark = (
        SparkSession.builder.appName(app_name)
        .config("spark.driver.extraClassPath", classpath)
        .config("spark.executor.extraClassPath", classpath)
        # Explicit interpreter path so Spark's worker subprocess doesn't
        # invoke bare "python" -- on Windows that can resolve to the
        # Microsoft Store's App Execution Alias stub instead of this venv's
        # real interpreter, which never connects back and times out.
        .config("spark.pyspark.python", sys.executable)
        .config("spark.pyspark.driver.python", sys.executable)
        .config("spark.mongodb.read.connection.uri", MONGO_URI)
        .config("spark.mongodb.read.database", MONGO_DB)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.log.level", "ERROR")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    log.info(f"Spark session started (PySpark {pyspark.__version__}, {len(jar_paths)} local jar(s))")
    return spark


def postgres_jdbc_url_and_props() -> tuple[str, dict]:
    from utils.connection import (
        POSTGRES_DATABASE,
        POSTGRES_HOST,
        POSTGRES_PASSWORD,
        POSTGRES_PORT,
        POSTGRES_USERNAME,
    )

    url = f"jdbc:postgresql://{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"
    props = {
        "user": POSTGRES_USERNAME,
        "password": POSTGRES_PASSWORD,
        "driver": "org.postgresql.Driver",
    }
    return url, props


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def discover_collections(mongo_db) -> list[str]:
    names = mongo_db.list_collection_names()
    collections = sorted(
        c for c in names if not any(c.startswith(p) for p in MONGO_SYSTEM_PREFIXES)
    )
    log.info(f"Discovered {len(collections)} collection(s) in '{MONGO_DB}': {collections}")
    return collections


def detect_incremental_column(
    sample_fields: list[str], override: Optional[str] = None
) -> Optional[str]:
    """Pick the watermark column for a collection: an explicit override wins,
    otherwise the first candidate (in priority order) actually present on a
    sample document. Returns None if the collection has none of them."""
    if override:
        return override if override in sample_fields else None
    for candidate in INCREMENTAL_COLUMN_CANDIDATES:
        if candidate in sample_fields:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Postgres metadata helpers
# ---------------------------------------------------------------------------
def table_exists(engine: Engine, table: str) -> bool:
    q = text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = :schema AND table_name = :table)"
    )
    with engine.connect() as conn:
        return bool(conn.execute(q, {"schema": BRONZE_SCHEMA, "table": table}).scalar())


def get_row_count(engine: Engine, table: str) -> int:
    if not table_exists(engine, table):
        return 0
    with engine.connect() as conn:
        return int(
            conn.execute(text(f'SELECT COUNT(*) FROM "{BRONZE_SCHEMA}"."{table}"')).scalar() or 0
        )


def has_unique_index_on(engine: Engine, table: str, column: str) -> bool:
    q = text("""
        SELECT 1
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey)
        WHERE n.nspname = :schema AND t.relname = :table
          AND a.attname = :column AND i.indisunique
          AND i.indnatts = 1
    """)
    with engine.connect() as conn:
        return (
            conn.execute(q, {"schema": BRONZE_SCHEMA, "table": table, "column": column}).fetchone()
            is not None
        )


def ensure_unique_id_index(engine: Engine, table: str) -> bool:
    """Make sure `_id` has a unique index so ON CONFLICT ("_id") works.
    Returns True if the table can be safely merged into, False if not
    (e.g. duplicate _id values already exist from a prior append-only run)."""
    if has_unique_index_on(engine, table, PRIMARY_KEY_COLUMN):
        return True
    index_name = f"{table}_{PRIMARY_KEY_COLUMN.strip('_')}_uidx"
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f'CREATE UNIQUE INDEX IF NOT EXISTS "{index_name}" '
                    f'ON "{BRONZE_SCHEMA}"."{table}" ("{PRIMARY_KEY_COLUMN}")'
                )
            )
        return True
    except SQLAlchemyError:
        log.warning(
            f'[{table}] could not create a unique index on "{PRIMARY_KEY_COLUMN}" '
            f"(likely duplicate values already present) -- upserts will fall back to append-only."
        )
        return False


def ensure_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{BRONZE_SCHEMA}"'))


# ---------------------------------------------------------------------------
# Control tables: bronze.etl_watermarks (incremental state) and
# bronze.etl_logs (per-collection run history)
# ---------------------------------------------------------------------------
def ensure_control_tables(engine: Engine) -> None:
    """Create the watermark + logs control tables if they don't exist yet.
    Fully idempotent -- safe to call on every run."""
    ensure_schema(engine)
    ddl_watermarks = f"""
        CREATE TABLE IF NOT EXISTS {BRONZE_SCHEMA}.{WATERMARK_TABLE} (
            table_name              TEXT PRIMARY KEY,
            incremental_column       TEXT,
            last_watermark_value     TIMESTAMPTZ,
            last_run_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_run_mode            TEXT,
            last_run_rows_inserted   BIGINT NOT NULL DEFAULT 0,
            last_run_rows_updated    BIGINT NOT NULL DEFAULT 0,
            updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """
    ddl_logs = f"""
        CREATE TABLE IF NOT EXISTS {BRONZE_SCHEMA}.{LOG_TABLE} (
            id                      BIGSERIAL PRIMARY KEY,
            run_id                  TEXT NOT NULL,
            table_name              TEXT NOT NULL,
            mode                    TEXT,
            incremental_column      TEXT,
            status                  TEXT NOT NULL,
            mongo_rows              BIGINT,
            postgres_rows_before    BIGINT,
            batch_rows              BIGINT,
            rows_inserted           BIGINT,
            rows_updated            BIGINT,
            skipped_rows            BIGINT,
            postgres_rows_after     BIGINT,
            columns_count           INT,
            validation_status       TEXT,
            validation_detail       TEXT,
            error                   TEXT,
            started_at              TIMESTAMPTZ,
            finished_at             TIMESTAMPTZ,
            duration_seconds        DOUBLE PRECISION,
            logged_at               TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """
    with engine.begin() as conn:
        conn.execute(text(ddl_watermarks))
        conn.execute(text(ddl_logs))
    log.info(f"Confirmed control tables exist: {BRONZE_SCHEMA}.{WATERMARK_TABLE}, {BRONZE_SCHEMA}.{LOG_TABLE}")


def get_watermark(engine: Engine, table: str) -> Optional[datetime]:
    q = text(f"SELECT last_watermark_value FROM {BRONZE_SCHEMA}.{WATERMARK_TABLE} WHERE table_name = :t")
    with engine.connect() as conn:
        row = conn.execute(q, {"t": table}).fetchone()
        return row[0] if row else None


def upsert_watermark(
    engine: Engine,
    table: str,
    incremental_column: Optional[str],
    last_value: Optional[datetime],
    mode: str,
    rows_inserted: int,
    rows_updated: int,
) -> None:
    q = text(f"""
        INSERT INTO {BRONZE_SCHEMA}.{WATERMARK_TABLE}
            (table_name, incremental_column, last_watermark_value, last_run_at,
             last_run_mode, last_run_rows_inserted, last_run_rows_updated, updated_at)
        VALUES (:table, :col, :last_value, now(), :mode, :inserted, :updated, now())
        ON CONFLICT (table_name) DO UPDATE SET
            incremental_column     = EXCLUDED.incremental_column,
            last_watermark_value   = COALESCE(EXCLUDED.last_watermark_value,
                                               {BRONZE_SCHEMA}.{WATERMARK_TABLE}.last_watermark_value),
            last_run_at            = EXCLUDED.last_run_at,
            last_run_mode           = EXCLUDED.last_run_mode,
            last_run_rows_inserted  = EXCLUDED.last_run_rows_inserted,
            last_run_rows_updated   = EXCLUDED.last_run_rows_updated,
            updated_at              = now()
    """)
    with engine.begin() as conn:
        conn.execute(
            q,
            {
                "table": table,
                "col": incremental_column,
                "last_value": last_value,
                "mode": mode,
                "inserted": rows_inserted,
                "updated": rows_updated,
            },
        )


def fetch_watermark_state(engine: Engine) -> list[dict]:
    q = text(
        f"SELECT table_name, incremental_column, last_watermark_value, last_run_at, "
        f"last_run_mode, last_run_rows_inserted, last_run_rows_updated "
        f"FROM {BRONZE_SCHEMA}.{WATERMARK_TABLE} ORDER BY table_name"
    )
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(q)]


def insert_log(engine: Engine, run_id: str, started_at: datetime, finished_at: datetime, r: CollectionResult) -> None:
    """Best-effort audit row in <schema>.etl_logs -- never let logging itself fail the run."""
    q = text(f"""
        INSERT INTO {BRONZE_SCHEMA}.{LOG_TABLE}
            (run_id, table_name, mode, incremental_column, status, mongo_rows,
             postgres_rows_before, batch_rows, rows_inserted, rows_updated,
             skipped_rows, postgres_rows_after, columns_count, validation_status,
             validation_detail, error, started_at, finished_at, duration_seconds)
        VALUES
            (:run_id, :table_name, :mode, :incremental_column, :status, :mongo_rows,
             :postgres_rows_before, :batch_rows, :rows_inserted, :rows_updated,
             :skipped_rows, :postgres_rows_after, :columns_count, :validation_status,
             :validation_detail, :error, :started_at, :finished_at, :duration_seconds)
    """)
    try:
        with engine.begin() as conn:
            conn.execute(
                q,
                {
                    "run_id": run_id,
                    "table_name": r.name,
                    "mode": r.mode,
                    "incremental_column": r.incremental_column,
                    "status": r.status,
                    "mongo_rows": r.mongo_rows,
                    "postgres_rows_before": r.postgres_rows_before,
                    "batch_rows": r.batch_rows,
                    "rows_inserted": r.rows_inserted,
                    "rows_updated": r.rows_updated,
                    "skipped_rows": r.skipped_rows,
                    "postgres_rows_after": r.postgres_rows_after,
                    "columns_count": r.columns,
                    "validation_status": r.validation_status,
                    "validation_detail": r.validation_detail,
                    "error": r.error_full or r.error,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "duration_seconds": r.seconds,
                },
            )
    except SQLAlchemyError:
        log.exception(f"[{r.name}] failed to write audit row to {BRONZE_SCHEMA}.{LOG_TABLE} (non-fatal)")


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
        .option("database", MONGO_DB)
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
            f"Database: [cyan]{MONGO_DB}[/cyan]  ->  Schema: [cyan]{BRONZE_SCHEMA}[/cyan]\n"
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

    mongo_db = mongo_client()
    engine = postgres_engine()
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