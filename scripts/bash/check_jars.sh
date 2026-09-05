#!/usr/bin/env bash
# ============================================================================
# check_jars.sh
# ----------------------------------------------------------------------------
# Verify that the local jars/ directory has every connector PySpark needs,
# AND that each jar's Scala-build matches the installed PySpark major
# version. This is the same check scripts/python/incremental.py does on startup,
# but exposed as a standalone command so you can validate the setup
# *before* paying the 30-second Spark session startup cost.
#
# Why this matters:
#   - mongo-spark-connector_2.12-10.x targets Spark 3.x
#   - mongo-spark-connector_2.13-11.x targets Spark 4.x
#   Mixing them produces the cryptic:
#       java.lang.NoSuchMethodError: ExpressionEncoder.resolveAndBind(...)
#   once for every collection you try to load. This script catches the
#   mismatch up front and prints the exact jars you need.
#
# Usage:
#   ./scripts/bash/check_jars.sh           # check, exit 1 on mismatch
#   ./scripts/bash/check_jars.sh --quiet   # only print on failure
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
JARS_DIR="${PROJECT_ROOT}/jars"

QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

# ----------------------------------------------------------------------------
# Output helpers.  Anything in stderr is treated as a real error by CI.
# ----------------------------------------------------------------------------
info() { [[ "$QUIET" -eq 0 ]] && printf "[check_jars] %s\n" "$1"; }
ok()   { [[ "$QUIET" -eq 0 ]] && printf "[check_jars] [OK] %s\n" "$1"; }
fail() { printf "[check_jars] [FAIL] %s\n" "$1" >&2; }

# ----------------------------------------------------------------------------
# Step 1: does the jars/ directory exist and contain any .jar at all?
# ----------------------------------------------------------------------------
if [[ ! -d "$JARS_DIR" ]]; then
    fail "Jars directory not found: ${JARS_DIR}"
    fail "Create it and drop the jars in (see comment block in scripts/python/incremental.py)."
    exit 1
fi

# `find ... -maxdepth 1` keeps us in jars/ itself, not recursive.
# `wc -l | tr -d ' '` strips whitespace so the count is a clean integer.
JAR_COUNT=$(find "$JARS_DIR" -maxdepth 1 -name "*.jar" -type f | wc -l | tr -d ' ')
if [[ "$JAR_COUNT" -eq 0 ]]; then
    fail "No .jar files found in ${JARS_DIR}"
    exit 1
fi
ok "Found ${JAR_COUNT} jar(s) in ${JARS_DIR}"

# ----------------------------------------------------------------------------
# Step 2: which Spark major version is installed?
#   `python -c "import pyspark; print(pyspark.__version__.split('.')[0])"`
# This calls into the active Python (the project's uv venv if you're in
# one, otherwise the system python). It always exits 0 because Python
# `print` succeeds; the value of the output is what we care about.
# ----------------------------------------------------------------------------
if ! command -v python >/dev/null 2>&1; then
    fail "python not found in PATH; cannot determine PySpark version."
    exit 1
fi

# `2>/dev/null` suppresses pyspark's noisy "WARN NativeCodeLoader" lines.
SPARK_MAJOR=$(python -c "import pyspark; print(pyspark.__version__.split('.')[0])" 2>/dev/null || echo "0")
if [[ "$SPARK_MAJOR" == "0" || -z "$SPARK_MAJOR" ]]; then
    fail "Could not detect PySpark major version. Is pyspark installed?"
    exit 1
fi
ok "Detected PySpark major version: ${SPARK_MAJOR}"

# ----------------------------------------------------------------------------
# Step 3: which Scala build does this Spark major version need?
#   Spark 4.x -> Scala 2.13  -> mongo-spark-connector_2.13
#   Spark 3.x -> Scala 2.12  -> mongo-spark-connector_2.12
# ----------------------------------------------------------------------------
case "$SPARK_MAJOR" in
    4) EXPECTED_SCALA="_2.13" ;;
    3) EXPECTED_SCALA="_2.12" ;;
    *)
        fail "Unsupported PySpark major version: ${SPARK_MAJOR} (expected 3 or 4)"
        exit 1
        ;;
esac
ok "Expected connector Scala build for Spark ${SPARK_MAJOR}.x: ${EXPECTED_SCALA}"

# ----------------------------------------------------------------------------
# Step 4: find the mongo-spark-connector jar and verify its Scala build.
#   We only check the FIRST connector we find -- you should not have
#   multiple connector builds in the same jars/ dir.
# ----------------------------------------------------------------------------
CONNECTOR_JAR=$(find "$JARS_DIR" -maxdepth 1 -name "mongo-spark-connector*.jar" -type f | head -1 || true)

if [[ -z "$CONNECTOR_JAR" ]]; then
    fail "No mongo-spark-connector*.jar found in ${JARS_DIR}"
    fail "Download the matching jar for Spark ${SPARK_MAJOR}.x:"
    fail "  https://repo1.maven.org/maven2/org/mongodb/spark/mongo-spark-connector${EXPECTED_SCALA}/"
    exit 1
fi

CONNECTOR_NAME=$(basename "$CONNECTOR_JAR")
info "Found connector: ${CONNECTOR_NAME}"

if [[ "$CONNECTOR_NAME" != *"$EXPECTED_SCALA"* ]]; then
    WRONG_MAJOR=$(( 7 - SPARK_MAJOR ))  # 3 if we have 4, 4 if we have 3
    fail "Connector/Spark version mismatch!"
    fail "  PySpark is ${SPARK_MAJOR}.x -> needs ${EXPECTED_SCALA}"
    fail "  jars/ has: ${CONNECTOR_NAME} (targets Spark ${WRONG_MAJOR}.x)"
    fail ""
    fail "  This exact mismatch causes:"
    fail "      java.lang.NoSuchMethodError: ExpressionEncoder.resolveAndBind(...)"
    fail ""
    fail "  Fix: delete ${CONNECTOR_NAME} and download the ${EXPECTED_SCALA} build."
    exit 1
fi
ok "Connector Scala build matches: ${CONNECTOR_NAME}"

# ----------------------------------------------------------------------------
# Step 5: required companion jars for the MongoDB Java driver.
#   These are version-pinned in the project's jars/ folder; we just
#   check that they're present, not that they match any particular version.
# ----------------------------------------------------------------------------
REQUIRED_DRIVER_JARS=(
    "bson-5.1.4.jar"
    "mongodb-driver-core-5.1.4.jar"
    "mongodb-driver-sync-5.1.4.jar"
)

MISSING=()
for jar in "${REQUIRED_DRIVER_JARS[@]}"; do
    if [[ ! -f "${JARS_DIR}/${jar}" ]]; then
        MISSING+=("$jar")
    fi
done

if (( ${#MISSING[@]} > 0 )); then
    fail "Missing required MongoDB driver jars: ${MISSING[*]}"
    fail "Download them from https://repo1.maven.org/maven2/org/mongodb/"
    exit 1
fi
ok "All required MongoDB driver jars present"

# ----------------------------------------------------------------------------
# Step 6: PostgreSQL JDBC driver.
#   The project ships postgresql.jar; we don't pin a version here because
#   any postgresql-*.jar works -- just confirm one exists.
# ----------------------------------------------------------------------------
PG_JAR=$(find "$JARS_DIR" -maxdepth 1 -name "postgresql*.jar" -type f | head -1 || true)
if [[ -z "$PG_JAR" ]]; then
    fail "No postgresql*.jar found in ${JARS_DIR}"
    fail "Download from https://jdbc.postgresql.org/download/"
    exit 1
fi
ok "PostgreSQL driver: $(basename "$PG_JAR")"

# ----------------------------------------------------------------------------
# Done.
# ----------------------------------------------------------------------------
ok "All jar checks passed. Safe to run scripts/python/incremental.py."
exit 0
