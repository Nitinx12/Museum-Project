# configs/

This folder contains project-wide configuration and environment variable loading. All pipeline scripts pull their connection settings from here.

---

## `connection.py` — Environment & Connection Config

Loads all required credentials from a `.env` file and exposes them as module-level constants. It also fails fast at import time if any required variable is missing, so misconfiguration is caught immediately before the pipeline runs.

**Exported constants:**

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST` | PostgreSQL server hostname |
| `POSTGRES_PORT` | PostgreSQL port |
| `POSTGRES_DATABASE` | Target database name |
| `POSTGRES_USERNAME` | PostgreSQL username |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `MONGO_URI` | Full MongoDB connection URI |
| `MONGO_DB` | MongoDB database name |

Also provides `get_mongo_db()` — a convenience function that returns a connected PyMongo database object.

---

## Setup

Create a `.env` file at the project root with the following variables:

```env
# PostgreSQL
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DATABASE=your_db
POSTGRES_USERNAME=your_user
POSTGRES_PASSWORD=your_password

# MongoDB
MONGO_URI=mongodb+srv://user:password@cluster.mongodb.net/
MONGO_DB=your_mongo_db
```

> **Note:** Never commit your `.env` file to version control. Add it to `.gitignore`.