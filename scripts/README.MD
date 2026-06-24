# scripts/

This folder contains the three ETL pipeline scripts that move data from MongoDB to a structured PostgreSQL data warehouse across three layers.

---

## `extract.py` — Bronze Layer (MongoDB → PostgreSQL)

Reads collections from MongoDB using PySpark and lands them into the `bronze` schema in PostgreSQL. Supports incremental loads via watermarking (only processes new/updated records) and full refreshes.

**Run:**
```bash
# Incremental — all collections
python -m scripts.extraction.extract

# Incremental — specific collection(s)
python -m scripts.extraction.extract --collection artist --collection museum

# Full refresh — all collections
python -m scripts.extraction.extract --full-refresh

# Full refresh — specific collection(s)
python -m scripts.extraction.extract --collection artist --full-refresh
```

---

## `transform.py` — Silver Layer (dbt)

Runs the dbt silver transformation pipeline on top of the bronze data. Builds SCD Type 2 snapshots first, then silver models, then runs 106 data quality tests with a 95% pass-rate gate.

**Run:**
```bash
python -m scripts.Transformation.transform
python -m scripts.Transformation.transform --full-refresh
```

---

## `load.py` — Gold Layer (dbt)

Builds the final gold layer dimensional models (`dim_artist`, `dim_artwork`, `dim_canvas_size`, `dim_museum`, `fct_sales`) from the silver layer and runs 41 data quality tests.

**Run:**
```bash
python -m scripts.loading.load
python -m scripts.loading.load --full-refresh
```

---

## Pipeline Order

```
extract.py  →  transform.py  →  load.py
(bronze)        (silver)         (gold)
```

Each script exits with code `1` on failure and writes a JSON failure report under `watermark/` for orchestrators like Airflow.