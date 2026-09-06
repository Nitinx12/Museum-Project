![Source](https://img.shields.io/badge/Source-MongoDB-47A248)
![Extraction](https://img.shields.io/badge/Extraction-PySpark%20%2B%20JDBC-E25A1C)
![Transformation](https://img.shields.io/badge/Transformation-dbt-FF694B)
![Warehouse](https://img.shields.io/badge/Warehouse-PostgreSQL-336791)
![Orchestration](https://img.shields.io/badge/Orchestration-Apache%20Airflow%203.x-017CEE)
![Runtime](https://img.shields.io/badge/Runtime-Docker%20Compose-2496ED)

<p align="center">
  <img src="assets/mona_lisa_logo.png" width="220" alt="Museum ETL logo">
</p>

<h1 align="center">Museum ETL</h1>

<p align="center">
  A medallion-architecture data platform that mirrors a museum's MongoDB source into Postgres,
  models it with dbt, and validates every layer orchestrated end-to-end by Airflow.
</p>

---

## Workflow at a glance

```mermaid
flowchart LR
    mongo[("MongoDB")] -->|PySpark| bronze[("Bronze")]
    bronze -->|dbt| silver[("Silver")]
    silver -->|dbt| gold[("Gold")]
    gold --> reports["Reports"]

    style mongo fill:#F76707,color:#fff
    style bronze fill:#A0522D,color:#fff
    style silver fill:#868E96,color:#fff
    style gold fill:#F1C40F,color:#000
    style reports fill:#4C6EF5,color:#fff
```

1. **Bronze** — raw collections mirrored 1:1 from MongoDB via PySpark, incrementally.
2. **Silver** — cleaned, conformed dbt models.
3. **Gold** — business-ready dimensions and facts.
4. Every layer is checked by both dbt tests and a hand-written SQL test suite.
5. Airflow schedules and sequences the whole chain inside Docker.

## Tech stack

- **Source**: MongoDB (museum collections)
- **Warehouse**: PostgreSQL
- **Extraction**: PySpark, incremental
- **Transformation**: dbt
- **Orchestration**: Apache Airflow
- **Runtime**: Docker Compose
- **Testing**: dbt tests + custom SQL test suite

## Prerequisites

- Docker and Docker Compose
- 4 GB+ RAM available to Docker
- Ports `8080` (Airflow) and `5432` (Postgres) free on the host

## Quick start

```bash
cd docker
docker compose up airflow-init   # one-time DB setup
docker compose up -d             # start everything
```

Open the Airflow UI at `http://localhost:8081` and trigger the DAG.

## Project structure

```
.
├── airflow/         # Airflow DAG definitions
├── docker/          # Compose files and service configs
├── museum_dbt/      # Silver/Gold dbt models and tests
├── tests/           # Hand-written SQL validation suite
├── scripts/         # Pipeline runners and bash helpers
│   ├── bash/        # Shell scripts (setup, checks, runner, monitor)
│   ├── ps1/         # PowerShell runner (pipeline_runner.ps1)
│   └── python/      # Core pipeline scripts (incremental.py, dbt_runner.py, run_sql_tests.py)
├── main.py          # Top-level pipeline entry point (Python)
└── docs/            # Detailed documentation
```

## Makefile targets

The top-level `Makefile` provides one-liner commands for every pipeline operation:

```bash
make help               # show all targets
make install            # install Python deps (uv sync)
make check-deps         # pre-flight: tools, .env, jars, Python deps
make test               # run unit tests
make lint               # syntax-check all .py files
make pipeline           # full ETL: bronze → silver → gold → tests
make pipeline-full      # full ETL with --full-refresh on every stage
make pipeline-bronze    # bronze load + tests only
make pipeline-tests     # load + build, skip test stages
make dry-run            # discover + count only (no writes)
make logs-summary       # report on logs/ directory
make logs-clean         # interactive log cleanup
make clean              # remove bytecode and pytest cache
```

Behind the scenes, `make pipeline` invokes `main.py`, which sequences the
stages in the same order as the Airflow DAG: bronze load, silver dbt,
gold dbt, SQL tests.


## Configuration

Copy `.env.example` to `.env` in `docker/` and set your MongoDB connection
string, Postgres credentials, and Airflow admin login before first run.

## Running tests

```bash
make test              # unit tests (pytest, no DB needed)
make lint             # Python syntax / AST check
```

The custom SQL suite under `tests/` runs automatically as part of the
Airflow DAG after each layer completes, and can also be triggered manually
via the `scripts/ps1/pipeline_runner.ps1` script described in `docs/pipeline.md`.

## Documentation

Full details live in `docs/`:

| Doc | Covers |
|---|---|
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, data flow, reliability principles |
| [`data_catalog.md`](docs/data_catalog.md) | Gold layer data dictionary and business logic |
| [`TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | Guide for resolving common pipeline failures |
| [`docker.md`](docs/docker.md) | Containers, services, startup sequence |
| [`scripts.md`](docs/scripts.md) | Guide to all pipeline, bash, and automation scripts |
| [`pipeline.md`](docs/pipeline.md) | Local pipeline runner (`scripts/ps1/pipeline_runner.ps1`) |
| [`utils.md`](docs/utils.md) | Shared connection/engine/logging helpers |

## Contributing

Open an issue or pull request for bug fixes, new dbt models, or additional
test coverage. Please run the full test suite locally before submitting.
