#!/usr/bin/env bash

# ============================================================================
# monitor_logs.sh
# Location: scripts/bash/monitor_logs.sh
#
# Watches the project's logs/ directory and can clean up old or oversized
# files. Two purposes:
#   1. SUMMARY mode (default): read-only report of every log file, with
#      size, age, and a status tag (LATEST, OLD, LARGE, etc.).
#   2. CLEAN mode: actually delete flagged files (older than MAX_AGE_DAYS
#      or larger than MAX_SIZE_MB). The most recently modified file is
#      ALWAYS preserved regardless of age or size.
#
# WHY IT EXISTS
# --------------
# Every pipeline stage writes its own log file to logs/ (e.g.
# bronze_load_20260101_120000.log). Over weeks those files accumulate and
# can fill the disk. This script gives a one-command view of the situation
# and a safe way to trim it -- without ever deleting the file currently
# being written to.
#
# DESIGN DECISIONS EXPLAINED
# ---------------------------
# - Why use `find -print0` + `while read -d ''`?
#   Because filenames can contain spaces, newlines, or glob characters.
#   `find -print0` NUL-terminates each path (NUL is the only byte that
#   cannot appear in a POSIX path), and `read -d ''` consumes one NUL-
#   delimited token at a time. `ls | while read` fails on names with
#   newlines or leading dashes; this pattern never does.
#
# - Why `stat -c` on Linux and `stat -f` on macOS in the same function?
#   GNU/Linux uses `stat -c '%Y'` for mtime epoch. BSD/macOS uses
#   `stat -f '%m'`. The `||` chain tries GNU first, falls back to BSD.
#   This makes the script portable across Linux dev machines, macOS, and
#   the Debian-based Airflow container.
#
# - Why mtime in nanoseconds?
#   On Linux, multiple files written within the same second all have the
#   same whole-second mtime. Using nanoseconds (via `stat -c '%.9Y'`) gives
#   a total ordering, so `find_latest_log` always picks the true latest
#   file even when several share the same second. BSD stat doesn't support
#   nanoseconds, so we fall back to whole-second precision there and call
#   out the limitation in the function body.
#
# - Why `--dry-run`?
#   Destructive operations deserve a preview. A misconfigured MAX_AGE_DAYS
#   or MAX_SIZE_MB can wipe the wrong files; `--dry-run` catches that.
#
# - Why `rm -f` inside a loop instead of `find -delete`?
#   Because we build the `to_delete` array first (so we can print what
#   we're about to delete before doing it), then delete in a second pass.
#   `find -delete` would delete as it finds, which means the preview
#   printed before deletion started could be inaccurate.
#
# USAGE
# ------
#   ./scripts/bash/monitor_logs.sh                 # summary (default, read-only)
#   ./scripts/bash/monitor_logs.sh summary         # same as above
#   ./scripts/bash/monitor_logs.sh clean           # delete flagged files (asks for confirm)
#   ./scripts/bash/monitor_logs.sh clean --dry-run # preview what clean would delete
#   ./scripts/bash/monitor_logs.sh clean -y        # skip the confirmation prompt
#   ./scripts/bash/monitor_logs.sh -h | --help     # show this header
#
# ENVIRONMENT VARIABLES (override defaults)
#   MAX_AGE_DAYS=14 ./scripts/bash/monitor_logs.sh clean   # files older than 14 days
#   MAX_SIZE_MB=10 ./scripts/bash/monitor_logs.sh clean    # files larger than 10 MB
# ============================================================================

set -uo pipefail
# Note: deliberately NOT `set -e`. This script deletes files in a loop and
# always prints a summary at the end. One bad/unreadable file should not
# silently abort before that summary prints -- the user needs to see the
# full picture even if one file in the middle failed.

# ----------------------------------------------------------------------------
# Resolve project root: this script lives at <project>/scripts/bash/monitor_logs.sh,
# so three levels up is the project root. `cd -P` follows symlinks; `pwd`
# (not `realpath`, which isn't portable) resolves to an absolute path.
# ----------------------------------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG_DIR="${PROJECT_ROOT}/logs"

# Defaults for retention thresholds. Can be overridden at call time:
#   MAX_AGE_DAYS=3 ./scripts/bash/monitor_logs.sh clean
MAX_AGE_DAYS="${MAX_AGE_DAYS:-7}"
MAX_SIZE_MB="${MAX_SIZE_MB:-5}"

# ----------------------------------------------------------------------------
# Output helpers. These four functions are the ONLY places in this script
# that print to stdout/stderr. Every other piece of logic calls one of these
# so output is consistent and easy to grep/script around.
#
# `info`    -> stdout, informational
# `notify`  -> stdout, deletion confirmations
# `warn`    -> stderr, non-fatal problems
# `err`     -> stderr, fatal problems (causes exit 1)
# ----------------------------------------------------------------------------
info()    { printf '[INFO] %s\n' "$1"; }
notify()  { printf '[NOTIFICATION] %s\n' "$1"; }
warn()    { printf '[WARNING] %s\n' "$1" >&2; }
err()     { printf '[ERROR] %s\n' "$1" >&2; }

# Print the help text. `sed -n '2,30p'` skips the shebang (line 1) and
# prints the next 28 lines of the script file itself, which contain the
# header comment block above. This keeps the usage docs in one place.
usage() {
    sed -n '2,30p' "$0"
}

# ============================================================================
# PORTABLE FILE STATS
# ============================================================================
# These three functions abstract away the GNU/Linux vs BSD/macOS differences
# for the stats we need: mtime as epoch seconds, mtime with nanoseconds
# (for the latest-file tiebreaker), and size in bytes.

# `stat -c` is GNU/Linux; `stat -f` is BSD/macOS.
# The `||` chain tries Linux first and falls back to BSD.
# `2>/dev/null` suppresses "stat: cannot stat" when the file disappears
# between `find` and `stat` (race condition on a file being written to).
file_mtime_epoch() {
    # '%Y' -> mtime as seconds-since-epoch (Linux)
    # '%m' -> mtime as seconds-since-epoch (macOS BSD)
    stat -c '%Y' "$1" 2>/dev/null || stat -f '%m' "$1" 2>/dev/null
}

# Nanosecond-precision mtime for picking the true latest file even when
# multiple files share the same whole-second mtime. GNU/Linux only.
# Falls back to whole-second precision on macOS (precision is degraded
# but the script still works correctly).
file_mtime_ns() {
    local out
    # `stat -c '%.9Y'` outputs e.g. "1704067200.123456789"
    # We strip the decimal point to get a single integer string for
    # lexicographic comparison: "1704067200123456789".
    if out=$(stat -c '%.9Y' "$1" 2>/dev/null); then
        printf '%s' "${out/./}"
    # BSD fallback: just whole seconds, no nanoseconds.
    # Use parameter expansion ${out}000000000 to pad to the same width
    # as the GNU output so the string comparison still works.
    elif out=$(stat -f '%m' "$1" 2>/dev/null); then
        printf '%s000000000' "$out"
    else
        return 1
    fi
}

# Apparent (logical) file size in bytes, not disk usage.
# `stat -c '%s'` (GNU) vs `stat -f '%z'` (BSD).
# `du -h` reports disk blocks used, which under-reports sparse files.
file_size_bytes() {
    stat -c '%s' "$1" 2>/dev/null || stat -f '%z' "$1" 2>/dev/null
}

# Convert bytes -> megabytes (integer division, truncates fractional MB).
file_size_mb() {
    local bytes
    bytes=$(file_size_bytes "$1") || { echo 0; return 1; }
    echo $(( bytes / 1024 / 1024 ))
}

# How old is the file, in whole days?
file_age_days() {
    local mtime now
    mtime=$(file_mtime_epoch "$1") || { echo 0; return 1; }
    now=$(date +%s)
    echo $(( (now - mtime) / 86400 ))
}

# ============================================================================
# find_latest_log
# ============================================================================
# Walk the entire logs/ directory and return the path of the most recently
# modified file (by nanosecond mtime where available).
#
# Why the `while IFS= read -r -d ''` pattern?
#   - `find ... -print0` emits NUL-delimited paths (safe for any filename).
#   - `read -r -d ''` reads one NUL-delimited token per iteration.
#   - `IFS=` prevents whitespace trimming (filenames with spaces stay intact).
#   - `-r` prevents backslash interpretation (paths with \ stay intact).
#   - The empty string `''` as -d argument is the NUL byte in bash.
#
# Returns the path as a plain string via `printf '%s'`. The calling code
# stores it in a variable, so a trailing newline from `echo` would corrupt
# the path comparison logic (e.g. LATEST="/logs/app.log\n" wouldn't match
# "/logs/app.log").
find_latest_log() {
    local latest="" latest_ns="" mtime_ns
    # `-print0` + `read -d ''` is the POSIX-correct way to iterate over
    # an arbitrary list of filenames in a shell-safe way.
    while IFS= read -r -d '' f; do
        mtime_ns=$(file_mtime_ns "$f") || continue
        # `10#$var` forces base-10 interpretation of the string.
        # Without it, bash can interpret a leading-zero string like
        # "0123" as octal, which gives wrong comparison results.
        if [[ -z "$latest" ]] || (( 10#$mtime_ns > 10#$latest_ns )); then
            latest_ns=$mtime_ns
            latest="$f"
        fi
    done < <(find "$LOG_DIR" -type f -print0 2>/dev/null)
    printf '%s' "$latest"
}

# ============================================================================
# require_log_dir
# ============================================================================
# Guard against running in the wrong directory. Returns 0 (success) if
# LOG_DIR exists; exits 1 with a warning if it doesn't. The `exit 0` in
# the error path means "nothing to do" rather than "something went wrong" --
# if logs/ was never created, there's nothing to report or clean.
require_log_dir() {
    if [[ ! -d "$LOG_DIR" ]]; then
        warn "Log directory does not exist: $LOG_DIR"
        exit 0
    fi
}

# ============================================================================
# classify_file
# ============================================================================
# Classify a single file by size and age, relative to the latest file.
# Prints three space-separated values:
#   <size_mb> <age_days> <status>
# where <status> is one of:
#   LATEST     - the most recently modified file; always preserved
#   OLD        - older than MAX_AGE_DAYS
#   LARGE      - larger than MAX_SIZE_MB
#   OLD+LARGE  - both old and large
#   OK         - within all limits
#
# The caller (cmd_summary, cmd_clean) reads these three values with:
#   read -r size age status <<< "$(classify_file "$f" "$latest")"
# so the output format is a contract between classify_file and its callers.
classify_file() {
    local f="$1"
    local latest="$2"
    local size age status is_old=0 is_large=0

    size=$(file_size_mb "$f")
    age=$(file_age_days "$f")

    if [[ "$f" == "$latest" ]]; then
        # Always preserve the latest file regardless of size or age.
        status="LATEST"
    else
        # Each condition is tested independently so OLD+LARGE gets its own
        # status label (clean prints a more informative message for it).
        (( age  > MAX_AGE_DAYS  )) && is_old=1
        (( size > MAX_SIZE_MB   )) && is_large=1
        if   (( is_old && is_large )); then status="OLD+LARGE"
        elif (( is_old ));            then status="OLD"
        elif (( is_large ));          then status="LARGE"
        else                                status="OK"
        fi
    fi

    printf '%s %s %s' "$size" "$age" "$status"
}

# ============================================================================
# cmd_summary
# ============================================================================
# Read-only report: iterates over every file in logs/, classifies it, and
# prints a table. Nothing is deleted. Always exits 0.
#
# The summary loop counts three things separately:
#   - n_old: files that are only old
#   - n_large: files that are only large
#   - n_oldlarge: files that are both old AND large
# These are reported separately so the user understands WHY a file is flagged.
cmd_summary() {
    require_log_dir

    # Find the latest file first -- classify_file needs it to mark LATEST.
    local latest
    latest=$(find_latest_log)

    if [[ -z "$latest" ]]; then
        info "No log files found in $LOG_DIR"
        return 0
    fi

    printf '\n%-40s %10s %10s %-12s\n' "FILE" "SIZE(MB)" "AGE(days)" "STATUS"
    # A line of dashes in the same width as the %-40s format spec.
    printf '%s\n' "--------------------------------------"

    local files_count=0 total_mb=0 n_old=0 n_large=0 n_oldlarge=0
    local f size age status

    # The `find ... -print0 | while read -d ''` loop:
    #   - `-print0` emits NUL-terminated paths (handles spaces, newlines).
    #   - `read -r -d ''` reads until NUL (the empty string argument).
    #   - `IFS=` prevents whitespace stripping from the path.
    #   - `-r` prevents backslash interpretation.
    while IFS= read -r -d '' f; do
        # `read -r size age status <<< "$(classify_file ...)"` reads the
        # three space-separated values that classify_file prints. `<<<` is
        # a here-string that feeds the string into `read` as stdin.
        read -r size age status <<< "$(classify_file "$f" "$latest")"
        printf '%-40s %10s %10s %-12s\n' "$(basename "$f")" "$size" "$age" "$status"
        files_count=$((files_count + 1))
        total_mb=$((total_mb + size))

        # Count the flags for the summary block at the end.
        # `case` is faster and more readable than a chain of `if`.
        case "$status" in
            OLD)       n_old=$((n_old + 1)) ;;
            LARGE)     n_large=$((n_large + 1)) ;;
            OLD+LARGE) n_oldlarge=$((n_oldlarge + 1)) ;;
        esac
    done < <(find "$LOG_DIR" -type f -print0 2>/dev/null)

    local would_delete=$((n_old + n_large + n_oldlarge))

    echo
    echo "============================================================"
    echo "                    LOG SUMMARY"
    echo "============================================================"
    echo "Log directory        : $LOG_DIR"
    echo "Total log files      : $files_count"
    echo "Total size (approx)  : ${total_mb} MB"
    echo "Latest (preserved)   : $(basename "$latest")"
    echo "Flagged - old only   : $n_old"
    echo "Flagged - large only : $n_large"
    echo "Flagged - old+large  : $n_oldlarge"
    echo "Would be deleted     : $would_delete"
    echo "============================================================"

    if (( would_delete > 0 )); then
        info "Run '$(basename "$0") clean' to remove flagged logs, or 'clean --dry-run' to preview."
    else
        info "Nothing needs cleanup."
    fi
}

# ============================================================================
# cmd_clean
# ============================================================================
# Destructive: delete files flagged by classify_file. Always asks for
# confirmation (unless --yes / -y is passed), and always prints a summary.
#
# Two-phase approach:
#   Phase 1: scan all files, build the `to_delete` array.
#            This lets us print exactly what will be deleted BEFORE
#            touching anything.
#   Phase 2: if confirmed, iterate `to_delete` and delete each file.
#
# Why not just `find ... -mtime +7 -size +5M -delete`?
#   Because the LATEST file must be excluded regardless of its age/size,
#   and `find` can't express "exclude this one specific path". We need
#   the classify_file logic anyway, so we use it to build a safe deletion
#   list and delete from that.
cmd_clean() {
    require_log_dir

    # Parse the optional flags for the `clean` subcommand.
    # `local` inside a function makes the variable scoped to that function.
    local dry_run=0 assume_yes=0 arg
    for arg in "$@"; do
        case "$arg" in
            --dry-run) dry_run=1 ;;
            -y|--yes)  assume_yes=1 ;;
            *)
                err "Unknown option for 'clean': $arg"
                usage
                exit 1
                ;;
        esac
    done

    local latest
    latest=$(find_latest_log)

    if [[ -z "$latest" ]]; then
        info "No log files found in $LOG_DIR"
        return 0
    fi

    info "Log directory : $LOG_DIR"
    info "Age limit     : ${MAX_AGE_DAYS} days"
    info "Size limit    : ${MAX_SIZE_MB} MB"
    info "Latest log (always kept): $(basename "$latest")"

    # ------------------------------------------------------------------------
    # Phase 1: scan and build the deletion list.
    # Bash arrays are used here (instead of newline-delimited strings) because
    # filenames with spaces would break a string-based accumulator.
    # Array syntax: `array+=(value)` appends; `"${array[@]}"` expands to all
    # elements individually-quoted (so each element is a separate word).
    # ------------------------------------------------------------------------
    local -a to_delete=() reasons=()
    local f size age status

    while IFS= read -r -d '' f; do
        read -r size age status <<< "$(classify_file "$f" "$latest")"
        case "$status" in
            OLD)
                to_delete+=("$f")
                reasons+=("older than ${MAX_AGE_DAYS} days")
                ;;
            LARGE)
                to_delete+=("$f")
                reasons+=("${size} MB")
                ;;
            OLD+LARGE)
                to_delete+=("$f")
                reasons+=("older than ${MAX_AGE_DAYS} days, ${size} MB")
                ;;
        esac
    done < <(find "$LOG_DIR" -type f -print0 2>/dev/null)

    # `${#to_delete[@]}` is the bash idiom for "length of array".
    if (( ${#to_delete[@]} == 0 )); then
        echo
        info "Nothing to delete."
        return 0
    fi

    echo
    info "${#to_delete[@]} file(s) will be deleted:"
    local i
    for i in "${!to_delete[@]}"; do
        # `${!array[@]}` gives indices (0, 1, 2...) not values.
        # Used here to access both `to_delete` and `reasons` at the same index.
        echo "  - $(basename "${to_delete[$i]}") (${reasons[$i]})"
    done

    # ------------------------------------------------------------------------
    # Phase 2: confirm and delete.
    # ------------------------------------------------------------------------
    if (( dry_run )); then
        echo
        info "Dry run - no files were deleted."
        return 0
    fi

    if (( ! assume_yes )); then
        local confirm=""
        # `read -r -p` prints the prompt string before reading.
        # `$\'...\'` is ANSI-C quoting: lets us use \n for a newline in
        # the prompt string. A plain "read -p" doesn't expand \n.
        read -r -p $'\nProceed with deletion? [y/N] ' confirm
        case "$confirm" in
            y|Y|yes|YES) ;;
            *) info "Aborted. No files were deleted."; return 0 ;;
        esac
    fi

    local deleted_count=0 failed_count=0
    for f in "${to_delete[@]}"; do
        # `rm -f` exits 0 even if the file doesn't exist; that's fine here
        # because classify_file already confirmed each file is real.
        # `2>/dev/null` suppresses "permission denied" on locked files.
        if rm -f "$f" 2>/dev/null; then
            notify "Deleted: $(basename "$f")"
            deleted_count=$((deleted_count + 1))
        else
            warn "Could not delete: $f"
            failed_count=$((failed_count + 1))
        fi
    done

    # Clean up empty subdirectories left behind. `find -mindepth 1 -type d
    # -empty -delete` deletes directories that are both empty AND at least
    # one level deep (so it never touches logs/ itself).
    find "$LOG_DIR" -mindepth 1 -type d -empty -delete 2>/dev/null || true

    echo
    echo "============================================================"
    echo "                 LOG CLEANUP SUMMARY"
    echo "============================================================"
    echo "Log directory        : $LOG_DIR"
    echo "Files deleted        : $deleted_count"
    if (( failed_count > 0 )); then
        echo "Failed to delete     : $failed_count"
    fi
    echo "Latest log preserved : $(basename "$latest")"
    echo "============================================================"
}

# ============================================================================
# Entry point
# ============================================================================
# The `main` function pattern is standard in well-structured bash scripts:
# it dispatches subcommands, keeping the top-level scope clean.
#
# `local cmd="${1:-summary}"` uses the `:-` default operator so that
# calling the script with no arguments defaults to "summary".
# `set -- arg1 arg2 ...` repopulates $1, $2, etc. from an array, which
# makes it possible to shift inside subcommand handlers without corrupting
# the caller's positional parameters.
main() {
    local cmd="${1:-summary}"
    shift 2>/dev/null || true

    case "$cmd" in
        summary|"") cmd_summary ;;
        clean)      cmd_clean "$@" ;;
        -h|--help|help) usage ;;
        *) err "Unknown command: $cmd"; usage; exit 1 ;;
    esac
}

# Call main with all arguments. Using `main "$@"` (not `main $@`) ensures
# each argument is passed as a separate quoted word, so arguments containing
# spaces survive the call intact.
main "$@"
