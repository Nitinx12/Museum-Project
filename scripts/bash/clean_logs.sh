#!/usr/bin/env bash
# ============================================================================
# clean_logs.sh
# ----------------------------------------------------------------------------
# Thin wrapper around scripts/bash/monitor_logs.sh that handles one extra case
# the monitor doesn't: archiving the logs/ directory before destructive
# cleanup, so a bad run can be debugged post-mortem.
#
# Why a wrapper and not just `monitor_logs.sh clean`?
#   - The monitor is the source of truth for "what's safe to delete".
#   - This wrapper adds a one-line tar.gz of the *current* logs to
#     logs/.archive/ before deletion, so we never lose forensics.
#   - The archive step is the only thing new here; everything else is
#     delegated to monitor_logs.sh.
#
# Usage:
#   ./scripts/bash/clean_logs.sh                       # dry run
#   ./scripts/bash/clean_logs.sh --apply               # actually delete
#   ./scripts/bash/clean_logs.sh --apply --yes         # no confirmation
#   ./scripts/bash/clean_logs.sh --archive-only        # archive, no delete
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"
ARCHIVE_DIR="${LOG_DIR}/.archive"
MONITOR="${SCRIPT_DIR}/monitor_logs.sh"  # scripts/bash/monitor_logs.sh

# ----------------------------------------------------------------------------
# Output helpers.
# ----------------------------------------------------------------------------
info() { printf "[clean_logs] %s\n" "$1"; }
fail() { printf "[clean_logs] [FAIL] %s\n" "$1" >&2; exit 1; }

# ----------------------------------------------------------------------------
# Argument parsing.
# ----------------------------------------------------------------------------
APPLY=0
ASSUME_YES=0
ARCHIVE_ONLY=0
while (( $# > 0 )); do
    case "$1" in
        --apply)        APPLY=1 ; shift ;;
        --yes|-y)       ASSUME_YES=1 ; shift ;;
        --archive-only) ARCHIVE_ONLY=1 ; shift ;;
        -h|--help)
            sed -n '2,18p' "$0"
            exit 0
            ;;
        *) fail "Unknown arg: $1" ;;
    esac
done

# ----------------------------------------------------------------------------
# Pre-flight.
# ----------------------------------------------------------------------------
[[ -d "$LOG_DIR" ]] || fail "Logs directory not found: ${LOG_DIR}"
[[ -f "$MONITOR" ]] || fail "Monitor script not found: ${MONITOR}"

# ----------------------------------------------------------------------------
# Archive the current logs/ directory to logs/.archive/. We tar the
# whole thing (including .archive) so the archive itself is captured
# at the time of the snapshot -- this is intentional; it gives you a
# recursive history of archives if you run the script repeatedly.
#
# The `tar` invocation uses:
#   -cz   : gzip-compressed
#   -f -  : write to stdout (so we can rename via the shell)
# The UTC timestamp matches the format used everywhere else in this
# project (cf. main.py / run_pipeline.sh).
# ----------------------------------------------------------------------------
archive_logs() {
    mkdir -p "$ARCHIVE_DIR"
    local ts
    ts=$(date -u +%Y%m%d_%H%M%S)
    local archive_path="${ARCHIVE_DIR}/logs_${ts}.tar.gz"

    info "Archiving ${LOG_DIR} -> ${archive_path}"
    # `-C` changes directory before tarring so the archive doesn't
    # embed absolute paths (which would make it hard to extract anywhere).
    if tar -czf "$archive_path" -C "$(dirname "$LOG_DIR")" "$(basename "$LOG_DIR")"; then
        info "Archive complete: $(du -h "$archive_path" | cut -f1)"
        return 0
    fi
    fail "Archive step failed; refusing to continue with deletion."
}

# ----------------------------------------------------------------------------
# Run the monitor's `summary` first (always) so the user sees the same
# output they would from running the monitor directly. Then either:
#   - just show the summary (default, --apply not set)
#   - archive + actually delete (--apply)
#   - archive only, no deletion (--archive-only)
# ----------------------------------------------------------------------------
info "Running monitor summary first..."
echo ""
bash "$MONITOR" summary
echo ""

if (( ARCHIVE_ONLY )); then
    archive_logs
    info "Archive-only mode: nothing was deleted."
    exit 0
fi

if (( ! APPLY )); then
    info "Dry-run only. Re-run with --apply to actually delete, or --archive-only to archive."
    info "Recommended:  $0 --apply"
    exit 0
fi

# Real run: archive first, then delete.
archive_logs

# Pass through --yes when the user asked us to skip the confirm prompt.
MONITOR_ARGS=(clean)
(( ASSUME_YES )) && MONITOR_ARGS+=(-y)

bash "$MONITOR" "${MONITOR_ARGS[@]}"
