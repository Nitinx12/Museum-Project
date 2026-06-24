# utils/

This folder contains shared utility modules used across all three pipeline stages (extraction, transformation, loading).

---

## `engine.py` — Database Connections

Provides ready-to-use connection objects for both databases.

- **`postgres_engine()`** — Returns a SQLAlchemy engine connected to PostgreSQL. Configured with connection pooling (`pool_size=5`, `max_overflow=10`) and `pool_pre_ping` to detect stale connections.
- **`mongo_client()`** — Returns a PyMongo database object connected to the configured MongoDB database.

Both functions log success/failure and raise on error so the pipeline fails fast if a connection can't be established.

---

## `logger.py` — Logging

Provides a consistent logger for all pipeline scripts.

**Usage:**
```python
from utils.logger import get_logger

log = get_logger(stage="extraction", name="my_script")
log.info("Something happened")
```

- `stage` must be one of: `extraction`, `transformation`, `loading`
- Creates a log file at `logs/<stage>/<name>_<timestamp>.log`
- Console output: `INFO` and above
- File output: `DEBUG` and above (more verbose)
- Format: `2024-06-01 12:00:00 | INFO     | your message here`

---

## Summary

| File | Purpose |
|------|---------|
| `engine.py` | PostgreSQL & MongoDB connection factories |
| `logger.py` | Structured logger with console + file output |