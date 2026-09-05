# Scripts

Plain-language explanation of what each script in `scripts/` does. For the
deeper design rationale, see `ARCHITECTURE.md`.

---

## `incremental.py`

**What it is:** The bronze loader. Copies every collection from MongoDB into
Postgres, using PySpark to move the data.

**What it does, in order:**
1. Finds every collection in the Mongo database automatically (or just the
   ones you name with `--tables`).
2. For each collection, figures out which timestamp column marks new/changed
   rows (`updated_at`, `updated_timestamp`, `created_at`, or
   `created_timestamp` — whichever exists).
3. Pulls only the rows changed since the last run (unless it's the first run,
   or you pass `--full-refresh`).
4. Cleans up anything Postgres can't store natively (Mongo's `_id`, and any
   nested objects/arrays get turned into text/JSON).
5. Merges the new rows into Postgres — updates existing rows, inserts new
   ones, never creates duplicates.
6. Double-checks the row count in Postgres actually matches what was
   expected.
7. Prints a results table and saves a full log.

**When you'd run it:** On a schedule (via Airflow), or manually to reload
data.

```bash
uv run scripts/python/incremental.py                     # everything
uv run scripts/python/incremental.py --tables orders,customers
uv run scripts/python/incremental.py --full-refresh      # ignore history, reload all
uv run scripts/python/incremental.py --dry-run           # preview only, writes nothing
```

**Needs:** a `jars/` folder with the matching Mongo + Postgres driver files
for whatever PySpark version is installed (the script checks this and tells
you exactly what's missing).

---

## `dbt_runner.py`

**What it is:** Runs your dbt project in the right order, and stops if
anything breaks.

**What it does, in order:**
1. Builds the silver models.
2. Tests the silver models.
3. Builds the gold models — but only if silver passed.
4. Tests the gold models.

If any step fails, it stops right there instead of building gold on top of a
broken silver layer.

**When you'd run it:** After `incremental.py` has refreshed bronze, to turn
that raw data into cleaned (silver) and reporting-ready (gold) tables.

```bash
uv run scripts/python/dbt_runner.py                  # full silver → gold run
uv run scripts/python/dbt_runner.py --skip-tests     # build only, no tests
uv run scripts/python/dbt_runner.py --silver-only    # stop after silver
uv run scripts/python/dbt_runner.py --gold-only      # skip silver (assumes it's already built)
uv run scripts/python/dbt_runner.py --full-refresh   # rebuild everything from scratch
```

**Needs:** `rich` installed, and a dbt project somewhere in the repo (it's
found automatically — you don't need to tell it where).

---

## `run_sql_tests.py`

**What it is:** A second, simpler test suite, separate from dbt's own tests.
Just plain `.sql` files that check something and complain if it's wrong.

**How a test works:** Each file does nothing if things look fine, and raises
a database error if they don't. For example, a test might check that no
ticket has a negative price — if one exists, the file raises an error and
that's a failure.

**How tests are organized:** One folder per layer under `tests/`:

```
tests/
  bronze/   ...
  silver/   ...
  gold/     ...
```

Drop a new `.sql` file into any of these folders and it runs automatically —
nothing else to configure.

**When you'd run it:** After loading or transforming data, to catch data
problems dbt's own tests might not cover.

```bash
uv run scripts/python/run_sql_tests.py                  # every test, every layer
uv run scripts/python/run_sql_tests.py --layer silver   # just the silver folder
```

**What you get:** A results table (pass/fail per test), a saved log file,
and — if anything failed — a single summary at the end listing every failure
together, so nothing gets lost in a long run.