#!/usr/bin/env bash
# ============================================================================
# run_pipeline.sh
# ----------------------------------------------------------------------------
# Bash equivalent of scripts/ps1/pipeline_runner.ps1 and main.py -- runs the
# full museum-etl pipeline in the same stage order as the Airflow DAG.
#
# Use this when you can't or don't want to use PowerShell (Linux, macOS,
# CI on a Linux runner, Git Bash on Windows where uv + PowerShell don't
# always cooperate) and don't want to go through Airflow.
#
#   ./scripts/bash/run_pipeline.sh                  # full pipeline
#   ./scripts/bash/run_pipeline.sh --skip-tests     # load + build, no tests
#   ./scripts/bash/run_pipeline.sh --bronze-only    # stop after bronze tests
#   ./scripts/bash/run_pipeline.sh --full-refresh   # --full-refresh everywhere
#   ./scripts/bash/run_pipeline.sh --check          # pre-flight only, don't run
#
# Each stage:
#   - Streams stdout to the terminal (so you see progress live)
#   - Persists a copy to logs/<stage>_<UTC-timestamp>.log
#   - Aborts the run on the first non-zero exit code
#
# A summary table is printed at the end covering every stage that ran.
# ============================================================================

set -euo pipefail

# ----------------------------------------------------------------------------
# Resolve PROJECT_ROOT regardless of where the user invoked us from.
# `cd -P` follows symlinks; `pwd` is the portable form of `realpath`.
# ----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "$LOG_DIR"

# ----------------------------------------------------------------------------
# Output helpers.
# ----------------------------------------------------------------------------
info()    { printf "[run_pipeline] %s\n" "$1"; }
section() { printf "\n\033[1;36m=== %s ===\033[0m\n" "$1"; }
ok()      { printf "\033[1;32m[PASS]\033[0m %s in %ss -- log: %s\n" "$1" "$2" "$3"; }
fail()    { printf "\033[1;31m[FAIL]\033[0m %s in %ss -- log: %s\n" "$1" "$2" "$3"; }

# ----------------------------------------------------------------------------
# Pre-flight: load .env and run dependency checks. A failed pre-flight
# aborts before we touch any data.
# ----------------------------------------------------------------------------
section "pre-flight"
SETUP_SCRIPT="${SCRIPT_DIR}/setup_env.sh"
if [[ -x "$SETUP_SCRIPT" ]]; then
    # `source` (not `bash`) so the exported vars are visible to every
    # subsequent `uv run` call in this shell.
    # shellcheck disable=SC1090
    source "$SETUP_SCRIPT" --quiet || {
        info "Aborting: .env is missing required variables."
        exit 2
    }
fi

CHECK_DEPS_SCRIPT="${SCRIPT_DIR}/check_dependencies.sh"
CHECK_ONLY=0
for arg in "$@"; do
    [[ "$arg" == "--check" ]] && CHECK_ONLY=1
done

if [[ -x "$CHECK_DEPS_SCRIPT" ]]; then
    if ! bash "$CHECK_DEPS_SCRIPT" --strict >/dev/null 2>&1; then
        info "Dependency check failed. Re-run scripts/bash/check_dependencies.sh for details."
        if (( CHECK_ONLY )); then
            bash "$CHECK_DEPS_SCRIPT" --strict
            exit 1
        fi
        info "Continuing anyway -- fix the warnings before the next run."
    else
        info "Dependency check passed."
    fi
fi

if (( CHECK_ONLY )); then
    info "--check set: running pre-flight only, not the pipeline."
    exit 0
fi

# ----------------------------------------------------------------------------
# Argument parsing. We keep this dead-simple: the four flags below match
# the PowerShell runner 1:1 so muscle memory transfers.
# ----------------------------------------------------------------------------
SKIP_TESTS=0
BRONZE_ONLY=0
FULL_REFRESH=0

while (( $# > 0 )); do
    case "$1" in
        --skip-tests)    SKIP_TESTS=1 ; shift ;;
        --bronze-only)   BRONZE_ONLY=1 ; shift ;;
        --full-refresh)  FULL_REFRESH=1 ; shift ;;
        -h|--help)
            sed -n '2,25p' "$0"
            exit 0
            ;;
        *) info "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

# ----------------------------------------------------------------------------
# Stage definition. Order MUST match the Airflow DAG and main.py.
#
# Each stage is a small bash array. We accumulate them in $STAGES as
# "name|argv..." strings so the runner loop can `eval` them later -- a
# tiny bit of indirection that lets us skip stages conditionally without
# a tangle of if/else.
# ----------------------------------------------------------------------------
STAGES=()

BRONZE_ARGS=(run scripts/python/incremental.py)
(( FULL_REFRESH )) && BRONZE_ARGS+=(--full-refresh)
STAGES+=("bronze_load|${BRONZE_ARGS[*]}")

if (( ! SKIP_TESTS )); then
    STAGES+=("test_bronze|run scripts/python/run_sql_tests.py --layer bronze")
fi

if (( ! BRONZE_ONLY )); then
    BUILD_ARGS=(run scripts/python/dbt_runner.py --skip-tests)
    (( FULL_REFRESH )) && BUILD_ARGS+=(--full-refresh)
    STAGES+=("build_silver_gold|${BUILD_ARGS[*]}")

    if (( ! SKIP_TESTS )); then
        STAGES+=("test_silver_gold|run scripts/python/run_sql_tests.py --layer silver --layer gold")
    fi
fi

# ----------------------------------------------------------------------------
# Stage execution loop.
#
# We use the same streaming pattern as main.py: Popen with line-by-line
# tee'ing to both terminal and log file. That gives the user real-time
# feedback on long-running stages (especially incremental.py, which can
# take minutes for a full refresh).
# ----------------------------------------------------------------------------
section "stages"
info "project root: ${PROJECT_ROOT}"
info "logs:         ${LOG_DIR}"
info "stages:       ${#STAGES[@]}"

declare -a STAGE_NAMES=()
declare -a STAGE_STATUSES=()
declare -a STAGE_DURATIONS=()
declare -a STAGE_LOGS=()

ALL_PASSED=1
for entry in "${STAGES[@]}"; do
    NAME="${entry%%|*}"
    ARGS="${entry#*|}"

    # UTC timestamp in the same shape as the PowerShell runner uses, so
    # the logs directory looks consistent regardless of which tool ran.
    TS=$(date -u +%Y%m%d_%H%M%S)
    LOG_FILE="${LOG_DIR}/${NAME}_${TS}.log"

    section "$NAME"
    info "uv ${ARGS}"

    # Read the argv string into an array. We use `read -ra` which is
    # POSIX-ish and handles quoted arguments correctly.
    read -ra ARGV <<< "$ARGS"

    START=$(date +%s)
    # `set +e` so we can capture a non-zero exit code without `set -e`
    # killing the script before we've recorded the failure.
    set +e
    ( cd "$PROJECT_ROOT" && uv "${ARGV[@]}" 2>&1 | tee "$LOG_FILE" )
    EXIT_CODE=${PIPESTATUS[0]}  # PIPESTATUS[0] is uv's exit code, not tee's
    set -e
    END=$(date +%s)
    DURATION=$(( END - START ))

    if (( EXIT_CODE == 0 )); then
        ok "$NAME" "$DURATION" "$LOG_FILE"
        STAGE_STATUSES+=("PASSED")
    else
        fail "$NAME" "$DURATION" "$LOG_FILE"
        STAGE_STATUSES+=("FAILED")
        ALL_PASSED=0
    fi

    STAGE_NAMES+=("$NAME")
    STAGE_DURATIONS+=("${DURATION}s")
    STAGE_LOGS+=("$LOG_FILE")

    # Fail-fast: stop on the first broken stage so we don't build gold
    # on top of broken silver, etc.
    if (( EXIT_CODE != 0 )); then
        info "Stopping pipeline: ${NAME} failed (exit ${EXIT_CODE})."
        break
    fi
done

# ----------------------------------------------------------------------------
# Summary. We print a fixed-width table so it survives copy-paste into
# chat / PRs.
# ----------------------------------------------------------------------------
section "summary"

printf "%-20s %-8s %-10s %s\n" "STAGE" "STATUS" "DURATION" "LOG"
printf "%-20s %-8s %-10s %s\n" "--------------------" "--------" "----------" "----"
for i in "${!STAGE_NAMES[@]}"; do
    printf "%-20s %-8s %-10s %s\n" \
        "${STAGE_NAMES[$i]}" \
        "${STAGE_STATUSES[$i]}" \
        "${STAGE_DURATIONS[$i]}" \
        "${STAGE_LOGS[$i]}"
done

if (( ALL_PASSED )); then
    info "Pipeline PASSED."
    exit 0
else
    info "Pipeline FAILED."
    exit 1
fi
