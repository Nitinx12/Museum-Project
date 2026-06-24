# Museum Art Sales Pipeline

An automated, tested, medallion-architecture data pipeline that turns raw MongoDB collections of artists, museums, artworks, and sales listings into a documented, query-ready PostgreSQL star schema — orchestrated end-to-end by Airflow in Docker.

![Source](https://img.shields.io/badge/Source-MongoDB-47A248)
![Extraction](https://img.shields.io/badge/Extraction-PySpark%20%2B%20JDBC-E25A1C)
![Transformation](https://img.shields.io/badge/Transformation-dbt-FF694B)
![Warehouse](https://img.shields.io/badge/Warehouse-PostgreSQL-336791)
![Orchestration](https://img.shields.io/badge/Orchestration-Apache%20Airflow%203.x-017CEE)
![Runtime](https://img.shields.io/badge/Runtime-Docker%20Compose-2496ED)

---

## Table of Contents

- [Problem](#problem)
- [Solution](#solution)
- [Architecture](#architecture)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Data Model](#data-model)
- [Data Quality](#data-quality)
- [Getting Started](#getting-started)
- [Running the Pipeline Manually](#running-the-pipeline-manually)
- [Example Analysis](#example-analysis)
- [Documentation Index](#documentation-index)
- [Known Limitations and Roadmap](#known-limitations-and-roadmap)

---

## Problem

The source data — seven MongoDB collections covering artists, museums, museum hours, canvas sizes, artworks, subjects, and product listings — has the problems most raw operational data has:

- Fields are untyped strings, with inconsistent casts and formats (e.g. `'01'` vs `'1'` for the same numeric ID).
- Records are duplicated at the source (MongoDB has repeat `work_id` values), and some collections accumulate a new row every time a single field changes rather than overwriting in place.
- Several fields are simply wrong: museum `city`/`state`/`postal` values are swapped or merged together, and weekday names contain typos.
- There is no current-state view of any of this — answering a question like "what's the average discount by art era" means hand-joining and cleaning seven raw collections from scratch, every time, with no guarantee the answer is even correct.
- Nothing is tested, scheduled, or repeatable. A one-off analysis script gives one person one answer once; it doesn't scale to a refreshed, trustworthy warehouse.

## Solution

A three-layer (bronze/silver/gold) pipeline that does this work once, automatically, on a schedule, with tests guarding every layer:

| Before | After |
|---|---|
| Hand-cleaned exports, one-off scripts | A repeatable pipeline: `extract.py` → `transform.py` → `load.py` |
| Manual re-pulls of entire collections | Watermark-based incremental loads at both the bronze and silver layers |
| Silent data bugs (typos, swapped fields, duplicate keys) | Fixed once in silver, with the fix and its root cause documented |
| No way to know if a load was "good" | 147 dbt tests (106 silver + 41 gold) gated at a 95% pass rate before the next layer runs |
| Ad-hoc queries against raw collections | A documented star schema (4 dimensions + 1 fact) ready for SQL or BI tools |
| Manual runs, remembered by whoever ran them last | Airflow DAG on a fixed schedule, with retries and failure reporting |

The result is a warehouse someone can query with confidence — `sql/` contains twenty ready-made analytical queries (revenue by canvas size, top artists by revenue, discount trends by era, and others) that run directly against gold with no further cleaning required.

---

## Architecture

```mermaid
flowchart TD
    MG[("MongoDB\n(source)")]:::db

    subgraph orchestration["Orchestration — Airflow in Docker"]
        DAGN["museum_project DAG\nMon / Wed / Fri, 13:00 IST"]:::dag
    end

    subgraph pipeline["Pipeline Stages"]
        EX["extract.py\nPySpark + JDBC"]:::task
        TR["transform.py\ndbt: SCD2 snapshot -> silver -> 106 tests"]:::task
        LD["load.py\ndbt: gold -> 41 tests"]:::task
    end

    subgraph warehouse["PostgreSQL Warehouse"]
        BR[("bronze schema")]:::wh
        SI[("silver schema")]:::wh
        GO[("gold schema\n(star schema)")]:::wh
    end

    MG --> EX --> BR
    BR --> TR --> SI
    SI --> LD --> GO
    GO --> SQLQ["sql/\nanalysis queries"]:::cons

    DAGN -. triggers .-> EX
    DAGN -. triggers .-> TR
    DAGN -. triggers .-> LD

    classDef db fill:#E6F1FB,stroke:#185FA5,color:#0C447C
    classDef dag fill:#FAEEDA,stroke:#854F0B,color:#633806
    classDef task fill:#FAECE7,stroke:#993C1D,color:#712B13
    classDef wh fill:#EEEDFE,stroke:#534AB7,color:#3C3489
    classDef cons fill:#E1F5EE,stroke:#0F6E56,color:#085041
```

Full system architecture, design principles, and deployment topology are in [`docs/Architecture.md`](docs/Architecture.md).

---

## Key Features

- **Incremental and idempotent at every layer** — a Mongo-side JSON watermark feeds bronze; a `MAX(updated_at)` watermark with a 3-day lookback feeds silver's dbt `merge`. Re-running a load never duplicates or corrupts data.
- **Deduplication tuned to each layer's actual failure mode** — including a documented production fix where casting must happen *before* deduplication, not after, to avoid a Postgres `MERGE cannot affect row a second time` error.
- **Historical tracking via dbt snapshots (SCD Type 2)**, independent of the current-state silver tables.
- **147 automated dbt tests** (106 silver, 41 gold) gated at a 95% pass rate, with every accepted exception explicitly documented rather than silently tolerated.
- **A documented star schema** — four dimensions and one fact table, fully rebuilt from silver on every run, ready for direct SQL or a BI tool.
- **Fully containerized orchestration** — Airflow with `CeleryExecutor`, Redis, and its own metadata Postgres, all in Docker, scheduled three times a week with automatic retries and JSON failure reports.
- **A six-document reference library in `docs/`** covering the incremental mechanics, the dimensional model, the container/orchestration setup, the testing strategy, and the overall architecture in depth.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Source | MongoDB |
| Extraction | PySpark (local mode), PyMongo, PostgreSQL JDBC driver |
| Warehouse | PostgreSQL (separate from the Airflow metadata database) |
| Transformation & testing | dbt (Postgres adapter), `dbt_utils` |
| Orchestration | Apache Airflow 3.x, Celery, Redis |
| Runtime | Docker / Docker Compose |
| Shared infra code | SQLAlchemy (connection pooling), `psycopg2-binary`, custom logger |

Full rationale and version detail: [`docs/Architecture.md` — Technology Stack](docs/Architecture.md#5-technology-stack).

---

## Project Structure

```
Museum
├─ airflow/          Airflow image, docker-compose.yaml, DAG (pipeline.py)
├─ configs/           connection.py — env-driven DB credentials
├─ datasets/          static/seed input data
├─ docs/              architecture and reference documentation (see index below)
├─ drivers/           postgresql.jar — JDBC driver for Spark writes
├─ main.py            project-level entry point
├─ museum_dbt/        dbt project — bronze sources, silver models, gold models, snapshots, tests
├─ notebooks/         exploratory analysis (bronze EDA)
├─ scripts/
│  ├─ extraction/      extract.py, backfill_timestamps.py   (bronze)
│  ├─ transformation/  transform.py                          (silver)
│  └─ loading/         load.py                                (gold)
├─ sql/               20 numbered ad-hoc analysis queries against gold
└─ utils/             engine.py (connections), logger.py
```

---

## Data Model

Gold is a classic star schema: `fct_sales` at the center, surrounded by `dim_artist`, `dim_artwork`, `dim_museum`, and `dim_canvas_size`.

| Table | Grain |
|---|---|
| `fct_sales` | One row per (artwork, canvas size) listing |
| `dim_artwork` | One row per artwork |
| `dim_artist` | One row per artist |
| `dim_museum` | One row per museum |
| `dim_canvas_size` | One row per canvas size |

Full ERD, relationships, and column-level business rules: [`docs/star_schema.md`](docs/star_schema.md) and [`docs/data_catlog.md`](docs/data_catlog.md).

---

## Data Quality

| Layer | Tests | Gate |
|---|---|---|
| Silver | 106 | 95% pass rate (2 known, documented warns accepted) |
| Gold | 41 | 95% pass rate, 0 warnings expected |

Tests come from three sources: dbt's built-in generic tests (`unique`, `not_null`, `accepted_values`, `relationships`), one custom generic test (`not_negative`, guarding price columns), and a singular assertion file per model. A failing gate stops the pipeline before bad data reaches the next layer. Full breakdown: [`docs/data_test.md`](docs/data_test.md).

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- A MongoDB instance with the source collections loaded (`artist`, `museum`, `museum_hours`, `canvas_size`, `work`, `product_size`, `subject`)
- A PostgreSQL JDBC driver placed in `drivers/` (or `JDBC_JAR_PATH` set to an existing one)

### 1. Configure application credentials

Create a `.env` file at the project root:

```env
# PostgreSQL (warehouse)
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DATABASE=your_db
POSTGRES_USERNAME=your_user
POSTGRES_PASSWORD=your_password

# MongoDB
MONGO_URI=mongodb+srv://user:password@cluster.mongodb.net/
MONGO_DB=your_mongo_db
```

### 2. Start the orchestration stack

```bash
# One-time: shared network between Airflow and your MongoDB / warehouse Postgres
docker network create museum_net

# Inside airflow/ — copy and fill in the Airflow-specific .env (Fernet key, etc.)
cp _env .env

# Build and start everything
docker compose up --build -d

# Watch the one-shot initializer
docker compose logs -f airflow-init
```

### 3. Open the UI and run

```
http://localhost:9100
```

Default admin credentials and the full service/network/volume breakdown are in [`docs/docker.md`](docs/docker.md) — change the default password before exposing the UI publicly.

```bash
docker compose exec airflow-scheduler airflow dags unpause museum_project
docker compose exec airflow-scheduler airflow dags trigger museum_project
```

---

## Running the Pipeline Manually

Each stage can also be run directly, outside Airflow:

```bash
# Bronze
python -m scripts.extraction.extract
python -m scripts.extraction.extract --full-refresh

# Silver
python -m scripts.transformation.transform
python -m scripts.transformation.transform --full-refresh

# Gold
python -m scripts.loading.load
python -m scripts.loading.load --full-refresh
```

> **Note:** `scripts/README.MD` documents the silver command as `python -m scripts.Transformation.transform` (capital `T`), but the actual package on disk is `scripts/transformation/` (lowercase). The lowercase form above matches the real directory and will work on case-sensitive filesystems (including inside the Docker image); the capitalized form in that README will not. Worth fixing one side or the other.

---

## Example Analysis

`sql/` contains twenty numbered queries written directly against gold, for example:

- `01_average_discount_by_era.sql`
- `08_top_artist_by_revenue.sql`
- `09_fct_sales_grain_audit.sql`
- `16_canvas_boundary_revenue_impact.sql`
- `20_full_star_schema_strees_test.sql`

These run as-is once the gold layer is built — no further cleaning or joining required.

---

## Documentation Index

| Document | Covers |
|---|---|
| [`docs/Architecture.md`](docs/Architecture.md) | System architecture, design principles, deployment topology |
| [`docs/incremental.md`](docs/incremental.md) | Watermark and merge mechanics, bronze through silver |
| [`docs/star_schema.md`](docs/star_schema.md) | Gold-layer dimensional model and ERD |
| [`docs/data_catlog.md`](docs/data_catlog.md) | Column-level catalog and business rules for every gold table |
| [`docs/data_test.md`](docs/data_test.md) | Full testing strategy and the 95% quality gates |
| [`docs/docker.md`](docs/docker.md) | Container build, Airflow services, networks, startup/teardown |

---

## Known Limitations and Roadmap

- `museum_hours`'s incremental filter checks only `updated_at`, not `COALESCE(updated_at, loaded_at)` like every other silver model — flagged in `docs/incremental.md`, not yet fixed.
- The `scripts.Transformation` vs `scripts.transformation` casing mismatch above (`scripts/README.MD` vs the actual package) should be reconciled.
- 106 silver and 41 gold dbt tests are reported by the pipeline, but only 66 and 35 respectively are accounted for by the schema and singular tests reviewed for `docs/data_test.md` — the rest are most likely snapshot or source tests not yet documented.
- No BI tool is currently connected to gold; it is the intended consumption point but isn't wired up in this repository today.
- `scripts/extraction/backfill_timestamps.py` exists as a manual utility but isn't part of the scheduled DAG.

---

Maintained by Nitin.