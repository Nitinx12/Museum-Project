#!/usr/bin/env bash
# ============================================================================
# docker_status.sh
# ----------------------------------------------------------------------------
# Quick health check for the Docker Compose stack defined in
# docker/compose.yml. The Airflow services are the interesting ones, but
# the two Postgres instances (Airflow metadata + museum warehouse) and
# Redis (Celery broker) are equally required -- a missing one means tasks
# will fail in subtle ways (e.g. worker can't reach the broker and times
# out instead of erroring cleanly).
#
# Usage:
#   ./scripts/bash/docker_status.sh                # all services
#   ./scripts/bash/docker_status.sh --watch 5      # poll every 5s (Ctrl+C to stop)
#   ./scripts/bash/docker_status.sh --service museum-postgres
#                                                       # filter to one service
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_ROOT}/docker/compose.yml"

# Parse args. We support a small, explicit set rather than getopts because
# the surface area is tiny and the long-form-only flags read better in
# muscle memory.
WATCH_INTERVAL=0
SERVICE_FILTER=""
while (( $# > 0 )); do
    case "$1" in
        --watch)
            WATCH_INTERVAL="${2:?--watch requires an interval in seconds}"
            shift 2
            ;;
        --service)
            SERVICE_FILTER="${2:?--service requires a service name}"
            shift 2
            ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) printf "[docker_status] Unknown arg: %s\n" "$1" >&2; exit 2 ;;
    esac
done

# ----------------------------------------------------------------------------
# Pre-flight.
# ----------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    printf "[docker_status] [FAIL] docker not found in PATH\n" >&2
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    printf "[docker_status] [FAIL] 'docker compose' v2 plugin missing\n" >&2
    exit 1
fi

if [[ ! -f "$COMPOSE_FILE" ]]; then
    printf "[docker_status] [FAIL] Compose file not found: %s\n" "$COMPOSE_FILE" >&2
    exit 1
fi

# ----------------------------------------------------------------------------
# Output helpers.
# ----------------------------------------------------------------------------
info() { printf "[docker_status] %s\n" "$1"; }

# ----------------------------------------------------------------------------
# Compose runs from the directory containing compose.yml. We resolve it
# once and `cd` there for every invocation.
# ----------------------------------------------------------------------------
COMPOSE_DIR="$(cd "$(dirname "$COMPOSE_FILE")" && pwd)"

# Services we always care about, in the order we want to display them.
# This list is intentionally a copy of the service names in compose.yml;
# if a service is renamed in compose, update this list too.
DEFAULT_SERVICES=(
    "postgres"
    "museum-postgres"
    "redis"
    "airflow-init"
    "airflow-api-server"
    "airflow-scheduler"
    "airflow-dag-processor"
    "airflow-triggerer"
    "airflow-worker"
)

# ----------------------------------------------------------------------------
# Render a single `docker compose ps` snapshot as a small table.
# Output columns: SERVICE, STATE, HEALTH, PORTS
# ----------------------------------------------------------------------------
render_status() {
    local label="$1"
    printf "\n=== %s ===\n" "$label"

    # Build the optional service filter argument.
    local svc_args=()
    if [[ -n "$SERVICE_FILTER" ]]; then
        svc_args+=("$SERVICE_FILTER")
    fi

    # `docker compose ps --format json` gives us structured output that
    # we can format ourselves. Older compose versions don't support
    # --format json -- fall back to the text table in that case.
    local raw
    if raw=$(docker compose -f "$COMPOSE_FILE" ps --format json "${svc_args[@]}" 2>/dev/null) \
       && [[ -n "$raw" ]]; then
        printf "%-26s %-12s %-12s %s\n" "SERVICE" "STATE" "HEALTH" "PORTS"
        printf "%-26s %-12s %-12s %s\n" "------------------------------" "------------" "------------" "-----"
        # `jq` is the standard tool for this, but it's not always
        # installed on Windows + Git Bash. We do a light-weight parse
        # with python instead -- it's a hard dep of this project so
        # it's always available.
        echo "$raw" | python -c '
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        s = json.loads(line)
    except json.JSONDecodeError:
        continue
    name   = s.get("Service", "?")
    state  = s.get("State", "?")
    health = s.get("Health", "-") or "-"
    ports  = s.get("Publishers") or []
    ports_str = ",".join(
        "{}:{}->{}/{}".format(p.get("PublishedPort","?"), p.get("TargetPort","?"), p.get("PublishedPort","?"), p.get("Protocol","?"))
        for p in ports
    ) if ports else "-"
    print("{:<26} {:<12} {:<12} {}".format(name, state, health, ports_str))
'
    else
        # Fallback: plain text output from `docker compose ps`.
        docker compose -f "$COMPOSE_FILE" ps "${svc_args[@]}" || true
    fi
}

# ----------------------------------------------------------------------------
# One-shot or watch mode.
# ----------------------------------------------------------------------------
if (( WATCH_INTERVAL > 0 )); then
    info "Watching every ${WATCH_INTERVAL}s (Ctrl+C to stop)..."
    while true; do
        clear
        render_status "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
        sleep "$WATCH_INTERVAL"
    done
else
    render_status "$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
fi
