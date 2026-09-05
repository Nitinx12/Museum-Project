#!/usr/bin/env bash
# ============================================================================
# check_dependencies.sh
# ----------------------------------------------------------------------------
# Pre-flight check for the museum-etl pipeline. Verifies the local
# environment is ready BEFORE the user spends 30s on a Spark session
# that was always going to fail.
#
# Checks (in order):
#   1. Required CLI tools on PATH
#          - python (3.13+)
#          - uv     (the project's package manager)
#          - docker + docker compose (only if --docker flag is passed)
#          - git
#   2. The .env file is present and has all required keys
#   3. The local jars/ directory is complete (delegates to check_jars.sh)
#   4. The Python project's runtime deps resolve (uv pip check)
#
# Usage:
#   ./scripts/bash/check_dependencies.sh              # everything except docker
#   ./scripts/bash/check_dependencies.sh --docker     # also verify docker stack
#   ./scripts/bash/check_dependencies.sh --strict     # treat warnings as errors
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CHECK_DOCKER=0
STRICT=0
for arg in "$@"; do
    case "$arg" in
        --docker) CHECK_DOCKER=1 ;;
        --strict) STRICT=1 ;;
        -h|--help)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *) printf "[check_deps] Unknown arg: %s\n" "$arg" >&2; exit 2 ;;
    esac
done

# ----------------------------------------------------------------------------
# Output helpers.
# FAIL counts as an error -> exit 1.
# WARN only matters under --strict, otherwise just informational.
# ----------------------------------------------------------------------------
info() { printf "[check_deps] %s\n" "$1"; }
ok()   { printf "[check_deps] [OK]   %s\n" "$1"; }
warn() { printf "[check_deps] [WARN] %s\n" "$1" >&2; }
fail() { printf "[check_deps] [FAIL] %s\n" "$1" >&2; }

# Tracks the worst severity we've seen so we can decide the exit code.
WORST=0   # 0 = ok, 1 = warn, 2 = fail

record_warn() { (( WORST < 1 )) && WORST=1; }
record_fail() { WORST=2; }

# ----------------------------------------------------------------------------
# Step 1: required CLI tools.
#   `command -v` is the POSIX-correct replacement for `which`; it works
#   the same on bash, zsh, and sh, and never prints a path to stdout if
#   the binary isn't found.
# ----------------------------------------------------------------------------
info "Checking required CLI tools..."

require_cmd() {
    local cmd="$1" min_version="${2:-}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        fail "$cmd not found in PATH"
        record_fail
        return
    fi
    local path
    path=$(command -v "$cmd")
    if [[ -n "$min_version" ]]; then
        local version
        case "$cmd" in
            python)  version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) ;;
            uv)      version=$("$cmd" --version 2>/dev/null | awk '{print $2}') ;;
            docker)  version=$("$cmd" --version 2>/dev/null | awk '{print $3}' | tr -d ',') ;;
            *)       version="?" ;;
        esac
        # Lexicographic compare is fine for "X.Y" version strings as long
        # as the major version isn't in double digits -- which it won't
        # be in our lifetime.
        if [[ "$version" < "$min_version" ]]; then
            fail "$cmd version $version is below minimum $min_version (at: $path)"
            record_fail
            return
        fi
        ok "$cmd $version (>= $min_version) at $path"
    else
        ok "$cmd at $path"
    fi
}

require_cmd python  "3.13"
require_cmd uv      "0.4.0"
require_cmd git
if (( CHECK_DOCKER )); then
    require_cmd docker     "20.10"
    # `docker compose` (v2, plugin) is the modern way; the old
    # `docker-compose` (v1, standalone) is deprecated. We only check v2.
    if docker compose version >/dev/null 2>&1; then
        ok "docker compose v2 plugin available"
    else
        fail "docker compose v2 plugin missing (install the 'docker-compose-plugin' package)"
        record_fail
    fi
fi

# ----------------------------------------------------------------------------
# Step 2: .env file. We delegate the heavy lifting to setup_env.sh in
# --check mode (a dry run that exits 1 if any required key is missing).
# ----------------------------------------------------------------------------
info "Checking .env file..."

SETUP_SCRIPT="${SCRIPT_DIR}/setup_env.sh"
if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
    if [[ -f "${PROJECT_ROOT}/.env.example" ]]; then
        warn ".env not found -- .env.example exists, copy it:  cp .env.example .env"
        record_warn
    else
        fail "No .env or .env.example at project root"
        record_fail
    fi
else
    # We don't `source` setup_env.sh here because that would actually
    # export the variables into THIS shell. Instead, run it in a subshell
    # that just validates the file (the script returns 1 on missing keys).
    if bash "$SETUP_SCRIPT" --quiet >/dev/null 2>&1; then
        ok ".env loaded successfully (all required keys present)"
    else
        fail ".env is missing required keys (see setup_env.sh output above)"
        record_fail
    fi
fi

# ----------------------------------------------------------------------------
# Step 3: jars directory. Delegate to check_jars.sh so the jar logic
# stays in one place.
# ----------------------------------------------------------------------------
info "Checking Spark/Mongo/Postgres JDBC jars..."

if [[ -x "${SCRIPT_DIR}/check_jars.sh" ]]; then
    if bash "${SCRIPT_DIR}/check_jars.sh" --quiet >/dev/null 2>&1; then
        ok "jars/ directory is complete (see check_jars.sh for details)"
    else
        fail "jars/ has issues (run scripts/bash/check_jars.sh for details)"
        record_fail
    fi
else
    warn "check_jars.sh not found or not executable -- skipping jar check"
    record_warn
fi

# ----------------------------------------------------------------------------
# Step 4: Python deps resolve. `uv pip check` validates that every
# declared package in pyproject.toml is installed AND that there are no
# version conflicts between them.
# ----------------------------------------------------------------------------
info "Checking Python dependency resolution..."

if [[ -f "${PROJECT_ROOT}/pyproject.toml" ]]; then
    if command -v uv >/dev/null 2>&1; then
        # `uv pip check` exits 1 if any package is missing or has a
        # conflicting version. We don't run a full `uv sync` here because
        # that's destructive (it can modify the venv).
        if (cd "$PROJECT_ROOT" && uv pip check >/dev/null 2>&1); then
            ok "Python dependencies resolve cleanly"
        else
            warn "Python dependency check failed -- run 'uv sync' to fix"
            record_warn
        fi
    else
        warn "uv not on PATH; skipping Python dependency check"
        record_warn
    fi
else
    warn "pyproject.toml not found; skipping Python dependency check"
    record_warn
fi

# ----------------------------------------------------------------------------
# Final report.
# ----------------------------------------------------------------------------
echo ""
case "$WORST" in
    0) ok "All checks passed. You're ready to run the pipeline." ; exit 0 ;;
    1)
        if (( STRICT )); then
            fail "Warnings present (--strict); failing the check."
            exit 1
        fi
        warn "Warnings present. The pipeline may still work, but review them above."
        exit 0
        ;;
    2) fail "One or more checks failed. Fix the issues above and retry." ; exit 1 ;;
esac
