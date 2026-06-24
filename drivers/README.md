# drivers/

This folder contains JDBC driver files required by PySpark to connect to PostgreSQL during the extraction stage.

---

## `postgresql.jar` — PostgreSQL JDBC Driver

PySpark cannot use Python-based database connectors (like `psycopg2`) for writing data — it requires a JDBC driver. This JAR is passed to Spark at runtime so it can write DataFrames directly to PostgreSQL via JDBC.

It is used exclusively by `extract.py`, which verifies the JAR exists before Spark even starts and raises a clear error if it's missing.

---

## If the JAR is missing

Download it from the official PostgreSQL JDBC site and place it here:

```
https://jdbc.postgresql.org/download/
```

Or point to an existing JAR elsewhere on your machine via an environment variable:

```bash
# Linux / Mac
export JDBC_JAR_PATH=/path/to/postgresql-42.x.x.jar

# Windows
set JDBC_JAR_PATH=C:\path\to\postgresql-42.x.x.jar
```

> **Note:** Do not commit the JAR to version control. Add `drivers/*.jar` to `.gitignore` and have each environment download it separately.