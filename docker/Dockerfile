# syntax=docker/dockerfile:1
#
# museum-etl Airflow image
#   base:   apache/airflow:3.3.1-python3.12  (CeleryExecutor, DAG Bundles, dag-processor)
#   adds:   Java (PySpark needs a JVM), dbt-core + dbt-postgres, pymongo
#
# Lives in docker/, but the BUILD CONTEXT is the project root (see
# `context: ..` in docker/compose.yml) so this can still COPY the sibling
# museum_dbt/ and pipeline/ folders. Paths below are all relative to that
# context, not to this file's own location.
#
# Build:   docker compose -f docker/compose.yml build     (from project root)
#     or:  cd docker && docker compose build
#     or:  docker build -f docker/Dockerfile -t museum-airflow:latest .   (from project root)

FROM apache/airflow:3.3.1-python3.12

USER root

# Java is required for PySpark's bronze extraction (MongoDB -> Postgres).
# Kept in its own layer so bumping requirements.txt doesn't re-run apt.
RUN apt-get update \
    && apt-get install -y --no-install-recommends default-jdk procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/default-java \
    PATH="/usr/lib/jvm/default-java/bin:${PATH}"

# uv, copied straight from Astral's distroless image — no pip/pipx bootstrap
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# uv has no --user mode (unlike pip): https://github.com/astral-sh/uv/issues/1584
# so this installs --system, as root, into the same interpreter the `airflow`
# user runs at container start.
COPY --chown=airflow:root docker/requirements.txt /requirements.txt
RUN uv pip install --system --no-cache -r /requirements.txt

# Bake the dbt project (silver/gold) and PySpark jobs (bronze) into the image
# so tasks can shell out to them without relying on a volume being present.
# (Both are siblings of docker/ at the project root — hence context: ..)
# NOTE: host folder is `museum_dbt/`, kept as `dbt` on the container side so
# existing DAG code / dbt invocations referencing /opt/airflow/dbt still work.
COPY --chown=airflow:root museum_dbt/ /opt/airflow/dbt/
# NOTE: host folder is `pipeline/` — update this line if your PySpark jobs
# actually live somewhere else (e.g. scripts/).
COPY --chown=airflow:root pipeline/ /opt/airflow/spark_jobs/

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER airflow

ENTRYPOINT ["/entrypoint.sh"]