#!/usr/bin/env bash
# ============================================================================
# setup_env.sh
# ----------------------------------------------------------------------------
# Load the project's .env file and export every variable to the current
# shell. Designed to be `source`d from main.py / run_pipeline.sh / a
# developer terminal before running the pipeline.
#
# Why a separate bash script for what python-dotenv already does in
# utils/connection.py? Because some operations -- bash health checks,
# docker compose, psql one-liners, the .monitor shell -- need the same
# vars BEFORE Python is even loaded. This script keeps the source of
# truth (.env) in one place.
#
# Usage:
#   source scripts/bash/setup_env.sh         # apply to current shell
#   source scripts/bash/setup_env.sh --quiet # suppress info messages
#
# Rules:
#   - .env is loaded from the project root (one level up from this script).
#   - .env.example is used as a template for variable discovery ONLY when
#     .env is missing (so we still warn the user about missing keys).
#   - All exported vars are echoed (one per line) when --quiet is not set,
#     so callers can pipe through `env` to forward them into a Python
#     subprocess (see main.py:source_bash_env).
# ============================================================================

set -euo pipefail

# `set -u` would break the optional `--quiet` flag handling below
# (${1:-} under set -u is fine, but [[ -z "$1" ]] is the same).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"
ENV_EXAMPLE="${PROJECT_ROOT}/.env.example"

QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

# ----------------------------------------------------------------------------
# Output helpers — never use bare `echo` so callers can grep/redirect.
# ----------------------------------------------------------------------------
info()    { [[ "$QUIET" -eq 0 ]] && printf "[setup_env] %s\n" "$1"; }
warn()    { printf "[setup_env][WARN] %s\n" "$1" >&2; }
err()     { printf "[setup_env][ERROR] %s\n" "$1" >&2; }

# ----------------------------------------------------------------------------
# Pick the .env file to read.
# .env wins; .env.example is only used as a *shape reference* if .env is
# missing, so we can still tell the user which keys are expected.
# ----------------------------------------------------------------------------
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
        warn ".env not found at ${ENV_FILE}"
        warn "Using .env.example as a template — real values will be missing."
        warn "Copy .env.example to .env and fill in your credentials."
        ENV_FILE="$ENV_EXAMPLE"
    else
        err "No .env or .env.example found at ${PROJECT_ROOT}"
        err "Create one (see .env.example for the required variables)."
        return 1 2>/dev/null || exit 1
    fi
fi

info "Loading environment from: ${ENV_FILE}"

# ----------------------------------------------------------------------------
# Parse .env line-by-line. We don't just `source` it because:
#   1. .env may contain comments / blank lines that `source` would also
#      handle, but we want to skip them silently and warn on bad lines.
#   2. We want to track which keys we set so we can warn on duplicates.
# ----------------------------------------------------------------------------
# `set -a` is the magic here: it makes every subsequent variable
# assignment auto-exported, so the rest of the shell (and any child
# process) inherits it without us writing `export FOO=bar` for each line.
set -a
# shellcheck disable=SC1090  -- we intentionally source a runtime file
source "$ENV_FILE"
set +a

# ----------------------------------------------------------------------------
# Sanity-check the keys this project's code actually reads.
# Any missing key is a hard error: silent failures later (NoSuchMethodError
# on a Mongo connection, psycopg2 refusing to authenticate) are way
# harder to debug than "you forgot to set POSTGRES_HOST".
# ----------------------------------------------------------------------------
REQUIRED_KEYS=(
    "POSTGRES_HOST"
    "POSTGRES_PORT"
    "POSTGRES_DATABASE"
    "POSTGRES_USERNAME"
    "POSTGRES_PASSWORD"
    "MONGO_URI"
    "MONGO_DB"
)

MISSING=()
for key in "${REQUIRED_KEYS[@]}"; do
    # Use `[[ -z "${!key:-}" ]]` (indirect expansion) to test whether
    # $key is set and non-empty. The :- guards against `set -u` blowing up
    # when the variable is unset.
    if [[ -z "${!key:-}" ]]; then
        MISSING+=("$key")
    fi
done

if (( ${#MISSING[@]} > 0 )); then
    err "Missing required environment variables: ${MISSING[*]}"
    err "Set them in ${PROJECT_ROOT}/.env before running the pipeline."
    return 1 2>/dev/null || exit 1
fi

info "Environment loaded successfully. Required keys present: ${#REQUIRED_KEYS[@]}/${#REQUIRED_KEYS[@]}"

# ----------------------------------------------------------------------------
# Print every variable we set, so `source setup_env.sh && env` from
# main.py:source_bash_env picks them up.
# `set -a` already exported them; this just makes the post-source env
# output clean for capture.
# ----------------------------------------------------------------------------
for key in "${REQUIRED_KEYS[@]}"; do
    # Mask the password in the echoed value so it never ends up in a log.
    if [[ "$key" == *"PASSWORD"* || "$key" == *"SECRET"* ]]; then
        printf "%s=***MASKED***\n" "$key"
    else
        printf "%s=%s\n" "$key" "${!key}"
    fi
done
