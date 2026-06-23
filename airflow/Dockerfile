# ─────────────────────────────────────────────────────────────────
#  Museum — Custom Airflow Image
#  [FIX 8] Base updated: 2.9.2 → 3.0.2  (matches docker-compose)
#  Extras : Java 17 (PySpark), PySpark 3.5, PyMongo, psycopg2
# ─────────────────────────────────────────────────────────────────
FROM apache/airflow:3.0.2

USER root

# ── Java 17 (required by PySpark) ────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-17-jdk-headless \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

USER airflow

# ── PySpark (317 MB tarball — own layer so it caches separately) ─
# --timeout 600  : wait up to 10 min per chunk (default is 15s)
# --retries 5    : retry failed chunks before giving up
RUN pip install --no-cache-dir \
        --timeout 600 \
        --retries 5 \
        pyspark==3.5.1

# ── All other Python dependencies ────────────────────────────────
COPY requirements.airflow.txt /tmp/requirements.airflow.txt
RUN pip install --no-cache-dir \
        --timeout 120 \
        --retries 3 \
        -r /tmp/requirements.airflow.txt