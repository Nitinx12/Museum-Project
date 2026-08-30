#!/usr/bin/env bash
# Custom entrypoint for the museum-etl Airflow image.
#
# It only does pre-flight waiting/diagnostics, then hands off to the
# official Airflow image entrypoint (/entrypoint, run under dumb-init)
# with whatever command compose passed in ($@ = api-server, scheduler,
# dag-processor, celery worker, triggerer, ...).
set -euo pipefail

wait_for_postgres() {
  local host="$1" port="$2" user="$3" label="$4"
  echo "[entrypoint] waiting for ${label} postgres (${host}:${port})..."
  until pg_isready -h "$host" -p "$port" -U "$user" -q; do
    sleep 2
  done
  echo "[entrypoint] ${label} postgres is up."
}

# Airflow's own metadata DB.
wait_for_postgres "${POSTGRES_HOST:-postgres}" "${POSTGRES_PORT:-5432}" \
  "${POSTGRES_USER:-airflow}" "airflow-metadata"

# Museum warehouse DB. Deliberately a *different* service name from Airflow's
# "postgres" so the two never collide (see MUSEUM_PG_SERVICE_NAME in compose.yml).
if [[ -n "${MUSEUM_PG_SERVICE_NAME:-}" ]]; then
  wait_for_postgres "${MUSEUM_PG_SERVICE_NAME}" "${MUSEUM_PG_PORT:-5432}" \
    "${MUSEUM_PG_USER:-museum}" "museum-warehouse"
fi

# Redis broker — only relevant to scheduler/worker/triggerer/api-server, not
# one-off CLI commands like `airflow db migrate`.
if [[ -n "${AIRFLOW__CELERY__BROKER_URL:-}" ]]; then
  REDIS_HOST="${REDIS_HOST:-redis}"
  REDIS_PORT="${REDIS_PORT:-6379}"
  echo "[entrypoint] waiting for redis (${REDIS_HOST}:${REDIS_PORT})..."
  until (exec 3<>"/dev/tcp/${REDIS_HOST}/${REDIS_PORT}") >/dev/null 2>&1; do
    sleep 2
  done
  echo "[entrypoint] redis is up."
fi

# Simple Auth Manager writes the generated admin password to this file the
# first time the api-server boots. Tail it once so it lands in `docker
# compose logs` instead of getting lost inside the container.
if [[ "${1:-}" == "api-server" ]]; then
  (
    PW_FILE="${AIRFLOW_HOME:-/opt/airflow}/simple_auth_manager_passwords.json.generated"
    for _ in $(seq 1 30); do
      if [[ -f "$PW_FILE" ]]; then
        echo "[entrypoint] Simple Auth Manager credentials (${PW_FILE}):"
        cat "$PW_FILE"
        break
      fi
      sleep 2
    done
  ) &
fi

exec /usr/bin/dumb-init -- /entrypoint "$@"