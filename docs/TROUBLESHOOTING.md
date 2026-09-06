# Troubleshooting Guide

This guide provides solutions for common failures encountered in the Museum ETL pipeline.

## 1. Ingestion Failures (`incremental.py`)

### PySpark Memory Issues
**Symptoms**: `OutOfMemoryError` or `Java heap space` errors in the logs.
**Cause**: The batch size from MongoDB is too large for the allocated Spark executor memory.
**Solution**: 
- Increase the memory limit for the `airflow-worker` container in `docker/compose.yml`.
- If running locally, set `PYSPARK_SUBMIT_ARGS` to include `--driver-memory 4g`.

### MongoDB Connection Errors
**Symptoms**: `pymongo.errors.ServerSelectionTimeoutError` or `Connection refused`.
**Cause**: Incorrect `MONGO_URI` or the MongoDB container is not running.
**Solution**: 
- Run `docker compose ps` to ensure the `mongo` service is healthy.
- Check the `.env` file for the correct URI and credentials.

### Postgres Merge Conflicts
**Symptoms**: `UniqueViolation` or `duplicate key value violates unique constraint`.
**Cause**: The `_id` in MongoDB was changed or duplicates were introduced without a proper primary key.
**Solution**: 
- Use `uv run main.py --full` to truncate the bronze table and reload it from scratch.

## 2. Transformation Failures (`dbt_runner.py`)

### Database Connection Timeout
**Symptoms**: `OperationalError: connection to server at "localhost" failed`.
**Cause**: Postgres is restarting or the connection pool is exhausted.
**Solution**: 
- Restart the Postgres container: `docker compose restart museum-postgres`.
- Check if there are too many open connections in the warehouse.

### dbt Model Compilation Error
**Symptoms**: `Compilation Error` or `Database Error` during `dbt run`.
**Cause**: A change in the Bronze schema broke a Silver model.
**Solution**: 
- Check the `logs/` directory for the specific SQL error.
- Verify that the column names in `bronze.*` still match the references in the Silver `.sql` files.

## 3. Validation Failures (`run_sql_tests.py`)

### `RAISE EXCEPTION` caught
**Symptoms**: `FAIL: Found tickets with negative price` (or similar).
**Cause**: Data quality invariant violated (e.g., a sale price is negative).
**Solution**: 
- Investigate the source data in MongoDB for that specific record.
- If the data is correct but the test is too strict, update the test file in `tests/<layer>/`.

### `ERROR` (DB Error)
**Symptoms**: `ERROR: relation "silver.artwork" does not exist`.
**Cause**: The test was run before the model was built.
**Solution**: 
- Ensure the pipeline is run in the correct order: `bronze_load` $\rightarrow$ `build_silver_gold` $\rightarrow$ `test_silver_gold`.

## 4. General Setup

### `.env` not loaded
**Symptoms**: `Missing required environment variables: POSTGRES_HOST ...`
**Cause**: `.env` is missing or has the wrong permissions.
**Solution**: 
- Copy `.env.example` to `.env` and fill in the credentials.
- Ensure the file is in the project root.
