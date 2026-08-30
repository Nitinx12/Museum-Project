<p align="center">
  <img src="assets/mona_lisa_logo.png" width="220" alt="Museum ETL logo">
</p>

<h1 align="center">Museum ETL</h1>

<p align="center">
  A medallion-architecture data platform that mirrors a museum's MongoDB source into Postgres,
  models it with dbt, and validates every layer — orchestrated end-to-end by Airflow.
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

## Quick start

```bash
cd docker
docker compose up airflow-init   # one-time DB setup
docker compose up -d             # start everything
```

Open the Airflow UI at `http://localhost:8080` and trigger the DAG.

## Documentation

Full details live in `docs/`:

| Doc | Covers |
|---|---|
| [`ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System design, data flow, reliability principles |
| [`docker.md`](docs/docker.md) | Containers, services, startup sequence |
| [`scripts.md`](docs/scripts.md) | What each pipeline script does |
| [`pipeline.md`](docs/pipeline.md) | Local pipeline runner (`pipeline_runner.ps1`) |
| [`utils.md`](docs/utils.md) | Shared connection/engine/logging helpers |