"""
mongo_extract.py
PySpark incremental ETL: MongoDB → PostgreSQL (bronze schema)

Watermark logic:
  • Per-collection JSON  →  watermark/<collection>.json
  • Only processes docs WHERE ts_col > last_watermark
  • Upsert via staging table → INSERT ON CONFLICT DO UPDATE
  • No-PK collections use row-hash dedup to prevent duplicates

Flow:
  MongoDB Collection
      ↓  PyMongo read
  Spark DataFrame
      ↓  Watermark filter  (ts_col > last_watermark)
      ↓  Row-hash dedup    (no-PK collections only)
  JDBC Write → bronze.{table}_staging_{run_id}
      ↓  SQL Merge
  Bronze Table  →  bronze.{table}
      ↓
  Save Watermark JSON

4 Run Modes
───────────────────────────────────────────────────────────────
  python -m scripts.extraction.extract
      Incremental — ALL collections, watermark applied

  python -m scripts.extraction.extract --collection artist [--collection museum ...]
      Incremental — NAMED collection(s) only, watermark applied

  python -m scripts.extraction.extract --full-refresh
      Full refresh — ALL collections, drop all tables,
      reset all watermarks, reload everything from scratch

  python -m scripts.extraction.extract --collection artist --full-refresh
      Full refresh — NAMED collection(s) only, drop those
      tables, reset their watermarks, reload from scratch
───────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import os
import sys
import re
import json
import hashlib
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd
from pymongo import MongoClient
from pyspark.sql import SparkSession, DataFrame
from pyspark.sql import functions as F
from sqlalchemy import text

# sys.path manipulation to ensure project root is in the path for imports, regardless of where the script is run from.
def _find_project_root() -> Path | None:
    current = Path(__file__).resolve().parent
    for _ in range(6):
        if (current / "configs" / "connection.py").exists():
            return current
        current = current.parent
    return None

_root = _find_project_root()
if _root is None:
    raise RuntimeError(
        "Could not locate project root. "
        f"Searched upward from: {Path(__file__).resolve()}"
    )
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

# Project imports
from configs.connection import (
    MONGO_URI,
    MONGO_DB,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DATABASE,
    POSTGRES_USERNAME,
    POSTGRES_PASSWORD,
)
from utils.engine import postgres_engine
from utils.logger import get_logger

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

ETL_SCHEMA    = os.getenv("ETL_SCHEMA",    "bronze")
ETL_TS_COL    = os.getenv("ETL_TS_COL",   "updated_at")
ETL_PK_COL    = os.getenv("ETL_PK_COL",   "id")
WATERMARK_DIR = Path(os.getenv("WATERMARK_DIR", "watermark"))

# Per-collection primary key mapping.
# Used for ON CONFLICT DO UPDATE (upsert) during the bronze merge.
# Set to None for collections with no single-column PK (composite keys).
# No-PK collections use row-hash dedup so incremental re-runs never
# produce duplicate rows — see _add_row_hash() and merge_staging_to_bronze().
COLLECTION_PK_MAP: dict = {
    "museum":        "museum_id",
    "museum_hours":  None,          # composite: museum_id + day_of_week  → row-hash dedup
    "subject":       "subject_id",
    "canvas_size":   "size_id",
    "work":          "work_id",
    "product_size":  None,          # composite: work_id + size_id        → row-hash dedup
    "artist":        "artist_id",
}
JDBC_JAR_PATH = os.getenv(
    "JDBC_JAR_PATH",
    str(_root / "drivers" / "postgresql.jar"),
)

# Fail fast: verify the JDBC JAR exists before Spark even starts.
# Without this check the script reads all MongoDB data successfully, then
# dies with ClassNotFoundException when it tries the first JDBC write.
if not Path(JDBC_JAR_PATH).is_file():
    raise FileNotFoundError(
        f"\n\nPostgreSQL JDBC JAR not found at:\n  {JDBC_JAR_PATH}\n\n"
        "Fix options:\n"
        "  1. Download the JAR and place it at the path above:\n"
        "       https://jdbc.postgresql.org/download/\n"
        "  2. Or point to an existing JAR via env var:\n"
        "       set JDBC_JAR_PATH=C:\\path\\to\\postgresql-42.7.3.jar   (Windows)\n"
        "       export JDBC_JAR_PATH=/path/to/postgresql-42.7.3.jar    (Linux/Mac)\n"
    )

ISO_FMT = "%Y-%m-%dT%H:%M:%S"

JDBC_URL = (
    f"jdbc:postgresql://{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"
)

# ─────────────────────────────────────────────────────────────────────────────
# Watermark helpers
# ─────────────────────────────────────────────────────────────────────────────

def _watermark_path(table: str) -> Path:
    WATERMARK_DIR.mkdir(parents=True, exist_ok=True)
    return WATERMARK_DIR / f"{table}.json"


def load_watermark(table: str) -> dict:
    path = _watermark_path(table)
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "table":          table,
        "ts_col":         ETL_TS_COL,
        "last_watermark": None,
        "last_run":       None,
        "rows_loaded":    0,
    }


def save_watermark(table: str, ts_col: str,
                   new_max: str | None, rows_loaded: int) -> None:
    path = _watermark_path(table)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "table":          table,
            "ts_col":         ts_col,
            "last_watermark": new_max,
            "last_run":       datetime.now().strftime(ISO_FMT),
            "rows_loaded":    rows_loaded,
        }, fh, indent=2)


def reset_watermark(table: str, log) -> None:
    """Delete the watermark file for a table so the next incremental run
    treats it as a first-ever run (last_watermark = None).
    Called on --full-refresh so post-refresh incrementals start clean."""
    path = _watermark_path(table)
    if path.exists():
        path.unlink()
        log.info("WATERMARK RESET : watermark/%s.json deleted", table)
    else:
        log.info("WATERMARK RESET : watermark/%s.json not found (already clean)", table)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _slugify(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"[\s\-]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_") or "col"


def _staging_name(table: str, run_id: str) -> str:
    return f"{table}_staging_{run_id}"


def _add_row_hash(sdf: DataFrame, exclude_cols: list[str] | None = None) -> DataFrame:
    """Add a _row_hash TEXT column — MD5 of every data column concatenated.
    Used as a surrogate unique key for no-PK collections so ON CONFLICT
    (_row_hash) DO NOTHING prevents duplicate rows on incremental re-runs.

    exclude_cols: columns to skip when building the hash (e.g. loaded_at,
    which changes every run and would make every row look new).
    """
    skip = set(exclude_cols or []) | {"_row_hash"}
    hash_cols = [c for c in sdf.columns if c not in skip]
    # Concat all columns as "col1=val1|col2=val2|..." then MD5
    concat_expr = F.concat_ws(
        "|",
        *[F.concat(F.lit(f"{c}="), F.coalesce(F.col(c).cast("string"), F.lit("NULL")))
          for c in hash_cols]
    )
    return sdf.withColumn("_row_hash", F.md5(concat_expr))

# ─────────────────────────────────────────────────────────────────────────────
# Spark session
# ─────────────────────────────────────────────────────────────────────────────

def get_spark(app_name: str = "MuseumETL") -> SparkSession:

    os.environ["PYSPARK_PYTHON"] = os.getenv("PYSPARK_PYTHON", sys.executable)
    os.environ["PYSPARK_DRIVER_PYTHON"] = os.getenv("PYSPARK_DRIVER_PYTHON", sys.executable)
    return (
        SparkSession.builder
        .appName(app_name)
        .master("local[*]")
        # Use extraClassPath instead of spark.jars so Spark does not try to
        # chmod/distribute the JAR via fetchFile -- that requires winutils.exe
        # on Windows and fails with FileNotFoundException in local mode.
        .config("spark.driver.extraClassPath", JDBC_JAR_PATH)
        .config("spark.executor.extraClassPath", JDBC_JAR_PATH)
        .config("spark.sql.legacy.timeParserPolicy", "LEGACY")
        .config("spark.driver.memory", "2g")
        .getOrCreate()
    )

# ─────────────────────────────────────────────────────────────────────────────
# MongoDB read
# ─────────────────────────────────────────────────────────────────────────────

def read_mongo_collection(
    spark: SparkSession, collection: str, log
) -> DataFrame | None:
    """
    Read a full MongoDB collection via PyMongo.
    Drops _id (not JDBC-serializable), slugifies column names.
    """
    try:
        client = MongoClient(MONGO_URI)
        docs   = list(client[MONGO_DB][collection].find({}, {"_id": 0}))
        client.close()

        if not docs:
            log.warning("Collection '%s' is empty", collection)
            return None

        pdf = pd.DataFrame(docs)

        # Slugify column names
        pdf.columns = [_slugify(c) for c in pdf.columns]

        # FIX: cast each column to string only where the value is not null,
        # preserving NaN/None so JDBC writes proper NULLs to Postgres.
        for col in pdf.columns:
            pdf[col] = pdf[col].where(pdf[col].isna(), pdf[col].astype(str))

        sdf = spark.createDataFrame(pdf)
        log.info(
            "MongoDB READ : %s  →  %d docs  |  cols: %s",
            collection, len(docs), sdf.columns,
        )
        return sdf

    except Exception as e:
        log.error("Failed to read collection '%s': %s", collection, e)
        log.debug(traceback.format_exc())
        return None

# ─────────────────────────────────────────────────────────────────────────────
# Watermark filter
# ─────────────────────────────────────────────────────────────────────────────

def apply_watermark_filter(
    sdf: DataFrame,
    ts_col: str,
    last_watermark: str | None,
    log,
    total: int = 0,
) -> tuple:
    """Keep only rows newer than last_watermark.
    Returns (filtered_df, rows_new) -- reuses the total already computed
    by the caller to avoid a redundant sdf.count() Spark job.
    """
    if last_watermark is None:
        log.info("WATERMARK : None (first run) — loading all %d rows", total)
        return sdf, total

    if ts_col not in sdf.columns:
        log.warning("WATERMARK : column '%s' not found — loading all rows", ts_col)
        return sdf, total
    cutoff    = F.to_timestamp(F.lit(last_watermark))
    filtered  = sdf.filter(
        F.to_timestamp(F.col(ts_col)) > cutoff
    )
    new_count = filtered.count()
    log.info(
        "WATERMARK : last=%s  →  %d new rows / %d skipped",
        last_watermark, new_count, total - new_count,
    )
    return filtered, new_count


def compute_new_max_ts(sdf: DataFrame, ts_col: str) -> str | None:
    """Return ISO max timestamp from the processed batch."""
    if ts_col not in sdf.columns:
        return None
    row = sdf.agg(
        F.max(F.to_timestamp(F.col(ts_col))).alias("max_ts")
    ).collect()[0]
    return row["max_ts"].strftime(ISO_FMT) if row["max_ts"] else None

# ─────────────────────────────────────────────────────────────────────────────
# Postgres helpers
# ─────────────────────────────────────────────────────────────────────────────

def ensure_schema(conn, schema: str, log) -> None:
    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    log.info("Schema ready → %s", schema)


def ensure_bronze_table(
    conn, schema: str, table: str,
    columns: list[str], pk_col, log,
) -> None:  # pk_col: str | None
    """
    CREATE TABLE IF NOT EXISTS with UNIQUE on pk_col (has-PK collections)
    or UNIQUE on _row_hash (no-PK collections).

    Also adds any columns that exist in the incoming data but are missing
    from the existing table (schema evolution).
    """
    col_defs = ",\n    ".join(f'"{c}" TEXT' for c in columns)

    if pk_col and pk_col in columns:
        # Has a single-column PK — unique constraint on that column
        unique_clause = (
            f',\n    CONSTRAINT "{table}_{pk_col}_uq" UNIQUE ("{pk_col}")'
        )
    else:
        # No PK — unique constraint on _row_hash for dedup
        unique_clause = (
            f',\n    CONSTRAINT "{table}_row_hash_uq" UNIQUE ("_row_hash")'
        )

    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS "{schema}"."{table}" (
            _etl_id  SERIAL,
            {col_defs}{unique_clause}
        )
    """))

    # Schema evolution: add any columns that are new since the last run
    result        = conn.execute(text(f"""
        SELECT column_name
        FROM   information_schema.columns
        WHERE  table_schema = :schema
        AND    table_name   = :table
    """), {"schema": schema, "table": table})
    existing_cols = {row[0] for row in result}

    for col in columns:
        if col not in existing_cols:
            conn.execute(text(
                f'ALTER TABLE "{schema}"."{table}" ADD COLUMN "{col}" TEXT'
            ))
            log.info("Schema evolution → added column '%s' to %s.%s", col, schema, table)

    log.info("Bronze table ready → %s.%s  (pk=%s)", schema, table, pk_col or "row_hash")


def merge_staging_to_bronze(
    conn, schema: str, table: str,
    staging: str, columns: list[str],
    pk_col, log,
) -> int:  # pk_col: str | None
    """INSERT ... SELECT FROM staging with conflict handling.

    Has-PK collections  → ON CONFLICT (pk_col) DO UPDATE  (upsert)
    No-PK  collections  → ON CONFLICT (_row_hash) DO NOTHING  (dedup)

    Returns rows merged.
    """
    col_list = ", ".join(f'"{c}"' for c in columns)

    if pk_col and pk_col in columns:
        # Standard upsert on primary key
        update_set = ", ".join(
            f'"{c}" = EXCLUDED."{c}"' for c in columns if c != pk_col
        ) or f'"{pk_col}" = EXCLUDED."{pk_col}"'
        sql = f"""
            INSERT INTO "{schema}"."{table}" ({col_list})
            SELECT {col_list} FROM "{schema}"."{staging}"
            ON CONFLICT ("{pk_col}") DO UPDATE SET {update_set}
        """
    else:
        # No PK — use row hash to silently skip exact duplicates
        sql = f"""
            INSERT INTO "{schema}"."{table}" ({col_list})
            SELECT {col_list} FROM "{schema}"."{staging}"
            ON CONFLICT ("_row_hash") DO NOTHING
        """

    conn.execute(text(sql))
    count = conn.execute(
        text(f'SELECT COUNT(*) FROM "{schema}"."{staging}"')
    ).scalar()
    log.info("MERGE complete → %d rows into %s.%s", count, schema, table)
    return count


def drop_staging(conn, schema: str, staging: str, log) -> None:
    conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{staging}"'))
    log.debug("Staging dropped → %s.%s", schema, staging)


def truncate_bronze_table(conn, schema: str, table: str, log) -> None:
    """DROP the bronze table before a full-refresh load so constraints rebuild cleanly.
    Used so that a full reload starts clean and doesn't accumulate
    stale rows from a previous run or maintain broken constraints."""
    conn.execute(text(f'DROP TABLE IF EXISTS "{schema}"."{table}" CASCADE'))
    log.info("DROPPED → %s.%s  (full-refresh)", schema, table)

# ─────────────────────────────────────────────────────────────────────────────
# Core extraction function
# ─────────────────────────────────────────────────────────────────────────────

def extract_collection(
    collection: str,
    spark: SparkSession,
    engine,
    full_load: bool = False,
) -> dict:
    log    = get_logger(stage="extraction", name=collection)
    table  = _slugify(collection)
    ts_col = _slugify(ETL_TS_COL)
    schema = ETL_SCHEMA

    # Resolve PK: check the per-collection map first, fall back to ETL_PK_COL.
    # None means no single-column PK -- merge will use plain INSERT (no upsert).
    _raw_pk = COLLECTION_PK_MAP.get(collection, ETL_PK_COL)
    pk_col  = _slugify(_raw_pk) if _raw_pk else None
    if pk_col is None:
        log.info(
            "PK col : no single-column PK for '%s' — "
            "using row-hash dedup (ON CONFLICT _row_hash DO NOTHING).",
            collection,
        )

    # Unique staging name per run — prevents parallel collection runs
    # from clobbering each other's staging table.
    run_id  = datetime.now().strftime("%Y%m%d%H%M%S")
    staging = _staging_name(table, run_id)

    base = dict(collection=collection, rows_total=0,
                rows_new=0, rows_loaded=0, failed=0)

    log.info("=" * 65)
    log.info("COLLECTION : %s", collection)
    log.info("TARGET     : %s.%s", schema, table)
    log.info("STAGING    : %s.%s", schema, staging)

    # 1. Read from mongo
    sdf = read_mongo_collection(spark, collection, log)
    if sdf is None:
        return base

    rows_total        = sdf.count()
    columns           = sdf.columns
    base["rows_total"] = rows_total

    # 2. Watermark
    wm      = load_watermark(table)
    if full_load:
        log.info("WATERMARK : --full-refresh — ignoring saved watermark and resetting")
        reset_watermark(table, log)
        last_wm = None
    else:
        last_wm = wm.get("last_watermark")

    # 3. Incremental filter
    # rows_total already computed above -- pass it in to avoid a 2nd count()
    sdf_new, rows_new = apply_watermark_filter(
        sdf, ts_col, last_wm, log, total=rows_total
    )
    base["rows_new"] = rows_new

    if rows_new == 0:
        log.info("No new rows after watermark filter — nothing to do.")
        return base

    # 3c. Add loaded_at timestamp — marks when each row entered the pipeline.
    # Done here (after watermark filter, before staging write) so every row
    # written in this batch gets the same run timestamp.
    sdf_new = sdf_new.withColumn(
        "loaded_at",
        F.lit(datetime.now().strftime(ISO_FMT)).cast("timestamp"),
    )
    columns = sdf_new.columns  # refresh after adding loaded_at

    # 3d. Deduplication on pk_col — guards against duplicate source docs
    # (e.g. work collection has duplicate work_id values in MongoDB).
    # Keep the last occurrence so the most recent data wins.
    if pk_col and pk_col in columns:
        before_dedup = sdf_new.count()
        sdf_new = sdf_new.dropDuplicates([pk_col])
        dupes = before_dedup - sdf_new.count()
        if dupes > 0:
            log.warning(
                "DEDUP : removed %d duplicate '%s' values from '%s' "
                "(MongoDB source has duplicates)",
                dupes, pk_col, collection,
            )
            rows_new = sdf_new.count()
            base["rows_new"] = rows_new

    # 3e. Row-hash dedup for no-PK collections or missing PKs.
    # Computes MD5 of all data columns (excluding loaded_at which changes
    # every run) and adds a _row_hash column.
    if pk_col is None or pk_col not in columns:
        sdf_new = _add_row_hash(sdf_new, exclude_cols=["loaded_at"])
        columns = sdf_new.columns   # refresh — _row_hash is now included
        log.info("ROW HASH : added _row_hash column for no-PK dedup (or missing PK)")

    # 3b. Ensure bronze schema exists before the JDBC write.
    # ensure_schema is also called in step 5, but Spark's JDBC writer needs
    # the schema to already exist when it creates the staging table.
    try:
        with engine.connect() as _conn:
            with _conn.begin():
                ensure_schema(_conn, schema, log)
    except Exception as _e:
        log.error("Could not create schema '%s': %s", schema, _e)
        base["failed"] = rows_new
        return base

    # 4. Write to staging via JDBC
    log.info("Writing %d rows → staging: %s.%s", rows_new, schema, staging)
    try:
        (
            sdf_new.write
            .format("jdbc")
            .option("url",      JDBC_URL)
            .option("dbtable",  f'"{schema}"."{staging}"')
            .option("user",     POSTGRES_USERNAME)
            .option("password", POSTGRES_PASSWORD)
            .option("driver",   "org.postgresql.Driver")
            # Explicit batch sizes — default is 1 row/roundtrip on some
            # driver versions, which makes large writes extremely slow.
            .option("batchsize",  "5000")
            .option("numPartitions", "4")
            .mode("overwrite")
            .save()
        )
        log.info("Staging write ✓")
    except Exception as e:
        log.error("JDBC staging write failed: %s", e)
        log.debug(traceback.format_exc())
        base["failed"] = rows_new
        return base

    # 5. Merge staging → bronze
    try:
        with engine.connect() as conn:
            with conn.begin():
                ensure_schema(conn, schema, log)
                
                # Full-refresh: drop the table completely before rebuilding 
                # so we get clean, updated constraints.
                if full_load:
                    truncate_bronze_table(conn, schema, table, log)
                    
                ensure_bronze_table(
                    conn, schema, table, list(columns), pk_col, log
                )
                
                rows_loaded = merge_staging_to_bronze(
                    conn, schema, table, staging, list(columns), pk_col, log
                )
                drop_staging(conn, schema, staging, log)

        base["rows_loaded"] = rows_loaded

    except Exception as e:
        log.error("Bronze merge failed: %s", e)
        log.debug(traceback.format_exc())
        # Best-effort: clean up orphaned staging table so it doesn't accumulate
        try:
            with engine.connect() as conn:
                with conn.begin():
                    drop_staging(conn, schema, staging, log)
        except Exception:
            pass
        base["failed"] = rows_new
        return base

    # ── 6. Save watermark ─────────────────────────────────────
    if rows_loaded > 0:
        new_max = compute_new_max_ts(sdf_new, ts_col)
        save_watermark(table, ts_col, new_max, rows_loaded)
        log.info(
            "WATERMARK SAVED : watermark/%s.json  (new_max=%s)", table, new_max
        )

    # ── 7. Summary ────────────────────────────────────────────
    log.info(
        "DONE  →  total=%d  new=%d  loaded=%d  failed=%d",
        rows_total, rows_new, rows_loaded, base["failed"],
    )
    log.info("=" * 65)
    return base

# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main(collections: list[str], full_load: bool = False) -> None:
    log = get_logger(stage="extraction", name="mongo_main")

    # Auto-discover all collections if none specified
    if not collections:
        with MongoClient(MONGO_URI) as client:
            collections = client[MONGO_DB].list_collection_names()
        log.info("Discovered %d collections: %s", len(collections), collections)

    log.info("Collections : %d", len(collections))
    if full_load and collections:
        log.info("Mode        : FULL REFRESH (drop+reload) — collections: %s", collections)
    elif full_load:
        log.info("Mode        : FULL REFRESH (drop+reload) — ALL collections")
    elif collections:
        log.info("Mode        : INCREMENTAL — collections: %s", collections)
    else:
        log.info("Mode        : INCREMENTAL — ALL collections")
    log.info("Schema      : %s", ETL_SCHEMA)
    log.info("TS col      : %s", ETL_TS_COL)
    log.info("PK col      : %s", ETL_PK_COL)
    log.info("JDBC JAR    : %s", JDBC_JAR_PATH)

    # Build shared Spark + Postgres engine
    spark  = get_spark()
    engine = postgres_engine()

    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    log.info("Postgres connected ✓")

    summaries: list[dict] = []
    for col in collections:
        summary = extract_collection(col, spark, engine, full_load=full_load)
        summaries.append(summary)

    spark.stop()
    engine.dispose()
    log.info("Spark stopped. Engine disposed.")

    # ── Run report ────────────────────────────────────────────
    log.info("")
    log.info("══════════════  RUN SUMMARY  ══════════════")
    totals = dict(rows_total=0, rows_new=0, rows_loaded=0, failed=0)
    for s in summaries:
        log.info(
            "%-20s  total=%-6d  new=%-6d  loaded=%-6d  failed=%d",
            s["collection"], s["rows_total"],
            s["rows_new"],   s["rows_loaded"], s["failed"],
        )
        for k in totals:
            totals[k] += s.get(k, 0)

    log.info("─" * 55)
    log.info(
        "TOTAL                total=%-6d  new=%-6d  loaded=%-6d  failed=%d",
        totals["rows_total"], totals["rows_new"],
        totals["rows_loaded"], totals["failed"],
    )
    log.info("═" * 55)

    if totals["failed"]:
        sys.exit(1)


if __name__ == "__main__":
    _argv = sys.argv[1:]

    # ── Mode flag ─────────────────────────────────────────────────────────────
    # --full-refresh  drop target table(s), reset watermark(s), reload all
    # --full-load     legacy alias for --full-refresh (kept for back-compat)
    _full_load = "--full-load" in _argv or "--full-refresh" in _argv

    # ── Collection filter ─────────────────────────────────────────────────────
    # --collection <name>  can be repeated for multiple tables, e.g.
    #   --collection artist --collection museum
    # If omitted, all collections are processed.
    _collections: list[str] = []
    for i, arg in enumerate(_argv):
        if arg == "--collection" and i + 1 < len(_argv):
            _collections.append(_argv[i + 1])

    main(_collections, _full_load)