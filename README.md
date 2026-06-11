
```
Museum
├─ configs
│  └─ connection.py
├─ datasets
├─ docs
│  └─ SQL Paintings Casestudy - Questions.pdf
├─ drivers
│  └─ postgresql.jar
├─ main.py
├─ museum_dbt
│  ├─ analyses
│  ├─ dbt_project.yml
│  ├─ macros
│  ├─ models
│  │  ├─ bronze
│  │  │  └─ source.yml
│  │  ├─ gold
│  │  │  └─ schema.yml
│  │  └─ silver
│  │     └─ schema.yml
│  ├─ package-lock.yml
│  ├─ packages.yml
│  ├─ README.md
│  ├─ seeds
│  ├─ snapshots
│  └─ tests
│     ├─ generic
│     ├─ gold
│     └─ silver
├─ notebooks
│  └─ museum_bronze_eda.ipynb
├─ pyproject.toml
├─ README.md
├─ scripts
│  ├─ extraction
│  │  ├─ backfill_timestamps.py
│  │  └─ extract.py
│  ├─ Loading
│  └─ Transformation
├─ utils
│  ├─ engine.py
│  └─ logger.py
└─ watermark
   └─ extract
      ├─ artist.json
      ├─ canvas_size.json
      ├─ museum.json
      ├─ museum_hours.json
      ├─ product_size.json
      ├─ subject.json
      └─ work.json

```