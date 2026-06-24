
```
Museum
├─ airflow
│  ├─ config
│  │  └─ airflow.cfg
│  ├─ dags
│  │  └─ pipeline.py
│  ├─ docker-compose.yaml
│  ├─ Dockerfile
│  ├─ README.md
│  └─ requirements.airflow.txt
├─ configs
│  ├─ connection.py
│  └─ README.md
├─ datasets
├─ docs
│  ├─ data_catlog.md
│  ├─ docker.md
│  ├─ incremental.md
│  └─ star_schema.md
├─ drivers
│  ├─ postgresql.jar
│  └─ README.md
├─ main.py
├─ museum_dbt
│  ├─ analyses
│  ├─ dbt_project.yml
│  ├─ macros
│  │  └─ generate_schema.sql
│  ├─ models
│  │  ├─ bronze
│  │  │  └─ source.yml
│  │  ├─ gold
│  │  │  ├─ dim_artist.sql
│  │  │  ├─ dim_artwork.sql
│  │  │  ├─ dim_canvas_size.sql
│  │  │  ├─ dim_museum.sql
│  │  │  ├─ fct_sales.sql
│  │  │  └─ schema.yml
│  │  └─ silver
│  │     ├─ artist.sql
│  │     ├─ canvas_size.sql
│  │     ├─ museum.sql
│  │     ├─ museum_hours.sql
│  │     ├─ product_size.sql
│  │     ├─ schema.yml
│  │     ├─ subject.sql
│  │     └─ work.sql
│  ├─ package-lock.yml
│  ├─ packages.yml
│  ├─ README.md
│  ├─ seeds
│  ├─ snapshots
│  └─ tests
│     ├─ generic
│     │  └─ not_negative.sql
│     ├─ gold
│     │  ├─ assert_dim_artist.sql
│     │  ├─ assert_dim_artwork.sql
│     │  ├─ assert_dim_canvas_size.sql
│     │  ├─ assert_dim_museum.sql
│     │  └─ assert_fct_sales.sql
│     └─ silver
│        ├─ assert_artist.sql
│        ├─ assert_canvas_size.sql
│        ├─ assert_museum.sql
│        ├─ assert_museum_hours.sql
│        ├─ assert_product_size.sql
│        ├─ assert_subject.sql
│        └─ assert_work.sql
├─ notebooks
│  ├─ museum_bronze_eda.ipynb
│  └─ README.MD
├─ pyproject.toml
├─ README.md
├─ scripts
│  ├─ extraction
│  │  ├─ backfill_timestamps.py
│  │  └─ extract.py
│  ├─ loading
│  │  └─ load.py
│  ├─ README.MD
│  └─ transformation
│     └─ transform.py
├─ sql
│  ├─ 01_average_discount_by_era.sql
│  ├─ 02_revenue_by_canvas_size.sql
│  ├─ 03_museum_artwork_vs_hours.sql
│  ├─ 04_above_median_by__nationalty.sql
│  ├─ 05_unknown_subject_artwork.sql
│  ├─ 06_weekend_museum_pricing.sql
│  ├─ 07_canvas_size_distribution.sql
│  ├─ 08_top_artist_by_revenue.sql
│  ├─ 09_fct_sales_grain_audit.sql
│  ├─ 10_canvas_bucket_boundary.sql
│  ├─ 11_historical_vs_living.sql
│  ├─ 12_city_museum.sql
│  ├─ 13_discount_derivate.sql
│  ├─ 14_multi_size_parsed.sql
│  ├─ 15_coalesce_nulls_aduit.sql
│  ├─ 16_canvas_boundary_revenue_impact.sql
│  ├─ 17_missing_metadata_orphan_analysis.sql
│  ├─ 18_museum_hours_artwork_correlation.sql
│  ├─ 19_is_in_museum_audit_flag.sql
│  ├─ 20_full_star_schema_strees_test.sql
│  └─ README.md
└─ utils
   ├─ engine.py
   ├─ logger.py
   └─ README.md

```