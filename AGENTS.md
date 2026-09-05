# AGENTS.md — Museum ETL

> **Audience**: AI coding agents and human contributors working on the
> museum-etl medallion data platform. This file is the single source of
> truth for *how* work is done here — not *what* the project does (see
> [`README.md`](README.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
> for that).
>
> **Scope**: Every directory under this repo. When a more specific rule
> applies, follow it; otherwise fall back to this file.

---

## 0. Project at a glance

```text
MongoDB  →  [scripts/python/incremental.py / PySpark]   →  Bronze (Postgres)
                                                                  ↓
                                                 [scripts/python/dbt_runner.py / dbt]
                                                                  ↓
                                                      Silver (cleaned models)
                                                                  ↓
                                                      Gold (star schema for BI)
                                                                  ↓
                                       [scripts/python/run_sql_tests.py / SQL files]
```

Everything ships inside Docker Compose (`docker/compose.yml`). The
Airflow DAG `museum_project` (`airflow/dags/museum_pipeline.py`) is the
canonical execution order. Three local runners reproduce the same order
without Airflow:

| Runner | Audience |
|---|---|
| `main.py` (project root) | Python-first; `uv run main.py` |
| `scripts/ps1/pipeline_runner.ps1` | Windows PowerShell 7+ users |
| `scripts/bash/run_pipeline.sh` | Linux, macOS, Git Bash on Windows |

The pre-flight bash helpers in `scripts/bash/` (`setup_env.sh`,
`check_dependencies.sh`, `check_jars.sh`, `docker_status.sh`,
`clean_logs.sh`) are shared by every runner and are safe to source
directly.

---

## 1. General rules (apply to *all* languages)

1. **Read before you write.** Always open the file you're about to
   modify; never edit blindly from memory.
2. **Match the local style.** Indentation, naming, quoting, and
   structure must match the file you're editing. If a neighbouring
   file uses 4-space indent and snake_case, do the same.
3. **No unsolicited refactors.** Don't reformat untouched code, rename
   symbols that aren't part of your task, or "modernize" working
   patterns. Scope = the change requested.
4. **Comment only when the *why* is non-obvious.** Don't narrate what
   the code does. A good comment captures a hidden constraint, a
   workaround, or a contract that isn't visible from the code itself.
5. **Never commit secrets.** `.env`, credentials, tokens, and `*.pem`
   files are in `.gitignore` for a reason. Use environment variables
   in code, never literals.
6. **Idempotency is sacred.** Bronze uses upserts; Silver/Gold use
   incremental `merge`. New code must remain safe to re-run — no
   duplicate rows, no append-only fallbacks.
7. **Fail fast, fail loud.** Scripts raise on the first broken stage
   (see `dbt_runner.py`, `incremental.py`); tests always run *all*
   checks and aggregate failures (see `run_sql_tests.py`). Don't
   silently swallow exceptions.
8. **No network at Spark runtime.** JDBC/connector jars live locally
   in `jars/`. Don't add code that fetches drivers at runtime.
9. **Tag-based selection.** dbt models are picked up by tag
   (`silver`, `gold`), not by filename. New models must carry the
   right tag.
10. **Test-only artifacts are permanent** unless the user says
    otherwise. Treat `tests/`, `museum_dbt/tests/`, and the SQL
    assertions you add as part of the codebase.

---

## 2. Bash (`scripts/bash/monitor_logs.sh`, `docker/entrypoint.sh`, ad-hoc scripts)

### Style

- **Shebang**: Always start with `#!/usr/bin/env bash` (or `#!/bin/bash`
  for the entrypoint — it runs in Debian-based images).
- **Strict mode**: `set -euo pipefail` at the top of every non-trivial
  script. If a script intentionally tolerates failures, comment *why*
  immediately above the `set` line.
- **Indentation**: 2 spaces. No tabs.
- **Variables**: Always quote expansions: `"${VAR}"`, `"$(cmd)"`.
  Prefer `"${var}"` over `"$var"` for readability and edge cases.
- **Naming**: `lower_snake_case` for locals, `UPPER_SNAKE_CASE` only
  for `export`ed env vars and read-only constants.
- **Functions**: `lower_snake_case`, named with a verb (`wait_for_postgres`,
  `print_summary`).

### Portability

- This codebase runs on **Linux containers, macOS developer hosts,
  and Git Bash on Windows**. Use portable `stat` (GNU + BSD), avoid
  `realpath` (use `cd -P`, `pwd`), avoid `sed -i` without backup
  suffix.
- If you must depend on GNU-only or BSD-only behavior, gate it with
  `uname -s` and a clear comment explaining the branch.

### Logging

- Echo informational lines with a `[label]` prefix matching the
  script's name (`[entrypoint]`, `[monitor_logs]`). Reserve bare
  stdout for the script's primary output (summary tables, etc.).
- Redirect per-script logs to `logs/<script>_<timestamp>.log` when
  invoked from the pipeline runner; preserve the user's stdout by
  using `tee`, not `>`.

### Health checks & waits

- For PostgreSQL: `pg_isready -h "$host" -p "$port" -U "$user" -q`
  inside an `until` loop. See `docker/entrypoint.sh:wait_for_postgres`.
- For Redis: open `/dev/tcp/host/port` (no extra binaries needed).
- Always bound retries with a sensible cap (`seq 1 30`) so a dead
  dependency doesn't hang the container forever.

### Examples in this repo

- `docker/entrypoint.sh` — wait loops, env defaults via
  `${VAR:-default}`, `exec` into the official entrypoint at the end.
- `scripts/bash/monitor_logs.sh` — flag/keep logic with portable `stat`, summary
  table at the end, no-op when `logs/` is missing.
- `scripts/bash/setup_env.sh` — sources `.env` with `set -a` auto-export,
  validates required keys, masks passwords in echoed output.
- `scripts/bash/check_jars.sh` — validates jars/ against installed PySpark
  version before any Spark work runs.
- `scripts/bash/check_dependencies.sh` — unified pre-flight: tools, env,
  jars, Python dep resolution.
- `scripts/bash/docker_status.sh` — `docker compose ps` with JSON parsing
  and optional `--watch` polling loop.
- `scripts/bash/run_pipeline.sh` — bash equivalent of `pipeline_runner.ps1`,
  fail-fast stage loop with `tee`-style streaming.
- `scripts/bash/clean_logs.sh` — wraps `scripts/bash/monitor_logs.sh clean`, adds
  tar.gz archive to `logs/.archive/` before deletion.

---

## 3. Python (`scripts/python/`, `main.py`, `airflow/dags/`, `museum_dbt/macros/`)

### Version & tooling

- Python **3.13+** (declared in `pyproject.toml:requires-python`).
- Package management: **uv only**. Never `pip install`, never
  `python -m venv`. Use `uv add`, `uv run`, `uv pip install`.
- Dependency declaration: `pyproject.toml`. Update it for any new
  third-party package.
- Formatter/linter: ruff (preferred) or the project's existing style.

### Style

- **Indentation**: 4 spaces. PEP 8.
- **Naming**: `snake_case` for functions/variables, `PascalCase`
  for classes, `UPPER_SNAKE_CASE` for module-level constants.
- **Imports**: stdlib → third-party → local, each group separated
  by a blank line. Absolute imports only (no relative `..` outside
  packages).
- **Type hints**: Required on every new public function signature.
  Use modern syntax (`list[str]`, `dict[str, int]`,
  `X | None`), not `Optional`, `List`, `Dict`.
- **Strings**: Double quotes by default. f-strings for interpolation.
  Triple double-quotes for docstrings.
- **Line length**: 100 chars (matches dbt-Python and modern Airflow
  defaults; ruff's default).

### Logging

- Use `logging.getLogger(__name__)`, never `print()` for anything
  that isn't a deliberate CLI table (see `scripts/python/dbt_runner.py` —
  it uses `rich` for the summary on purpose).
- Stream + persist: pipe live output to stdout *and* to a
  timestamped `logs/<script>_<UTC-timestamp>.log`.

### CLI conventions

- Argument parsing: `argparse` with explicit `help=` strings on every
  argument. Make flags repeatable (`action="append"`) where the
  underlying command supports it (see `--layer` in
  `scripts/python/run_sql_tests.py`).
- Exit codes: `0` on success, non-zero on any failure. No silent
  exit-0 paths.
- Long-running output: prefer streaming line-by-line over
  `subprocess.run(..., capture_output=True)` so users see progress.
  See `airflow/dags/museum_pipeline.py:_run` for the canonical
  pattern.

### Error handling

- Raise concrete exceptions (`RuntimeError`, `ValueError`,
  `subprocess.CalledProcessError`) — never bare `Exception`.
- Catch only what you can recover from; let the rest propagate.
- Validation errors should carry the *offending value* and the
  *expected pattern* in the message — see the version-mismatch
  check in `scripts/python/incremental.py`.

### PySpark specifics

- SparkSession construction is centralised in `scripts/python/incremental.py`;
  don't create new ones elsewhere.
- Type sanitization: `_id` → `str`, nested structs/arrays → `json.dumps`.
  This is documented in `docs/ARCHITECTURE.md §4` and must not be
  bypassed.
- Watermark detection order is **fixed**:
  `updated_at → updated_timestamp → created_at → created_timestamp`.
  Don't reorder or rename.

### Airflow DAG conventions

- DAG id format: `museum_project` (single DAG, fixed id).
- Schedule: cron string in `airflow/dags/museum_pipeline.py:schedule`.
  Update there if cadence changes — never via Airflow UI alone.
- Tasks are `@task`-decorated functions returning nothing; the
  shared `_run()` helper invokes the project's CLI scripts via
  `subprocess.run`.
- Path resolution: use `Variable.get("MUSEUM_PROJECT_ROOT", ...)`.
  Don't hardcode container paths in business logic.

### Examples in this repo

- `main.py` (project root) — top-level local runner; same stage order
  as the DAG, with `--skip-tests`, `--bronze-only`, `--full`, and
  `--dry-run` flags. Sources `scripts/bash/setup_env.sh` to export
  `.env` before any `uv` call.
- `scripts/python/incremental.py` — type hints everywhere, rich table
  for results, watermark table updates, exception path writes a log
  row even on failure.
- `scripts/python/dbt_runner.py` — stage ordering with hard stops,
  rich summary table, per-stage log files.
- `scripts/python/run_sql_tests.py` — auto-discovery, per-test
  transactions, single aggregated exception at the end.
- `airflow/dags/museum_pipeline.py` — minimal DAG, four tasks,
  fail-fast chain.

---

## 4. SQL — bronze control tables

### Style

- **Case**: `snake_case` for all identifiers (`etl_watermarks`,
  `etl_logs`, `bronze.products`).
- **Quoting**: never quote identifiers unless they collide with a
  reserved word. Prefer bare names.
- **Commas**: leading commas are *not* used here — stick to trailing
  commas (the dominant style in this repo).
- **Keywords**: `UPPER_CASE` for SQL keywords (`SELECT`, `FROM`,
  `INSERT ... ON CONFLICT`).
- **Indentation**: 2 spaces for major clauses; align `AS` aliases
  when the projection has more than three columns.

### Patterns

- **Upsert**: `INSERT ... ON CONFLICT ("_id") DO UPDATE SET ...`
  is the canonical merge pattern. See `scripts/python/incremental.py`.
- **Row-count validation**: always `SELECT COUNT(*)` *after* the
  write, never trust the writer's reported count.
- **Watermark**: `etl_watermarks` is one row per collection; never
  partial-updates it — replace the row in one statement.
- **Audit log**: `etl_logs` appends one row per collection per run,
  including failed runs. Don't filter failures out.

### Comments

- SQL comments live **above** the clause they document.
- Use `--` (single dash) for one-liners, never `/* */` unless you're
  commenting out a block during a temporary investigation.

---

## 5. SQL — dbt models (`museum_dbt/models/`)

### Structure

```
museum_dbt/
├── models/
│   ├── bronze/source.yml       # source definitions only
│   ├── silver/                 # cleaned/conformed models
│   │   ├── *.sql               # one model per file
│   │   └── schema.yml          # docs + tests
│   └── gold/                   # business-ready star schema
│       ├── *.sql
│       └── schema.yml
├── macros/                     # reusable Jinja
├── seeds/, snapshots/, analyses/
└── tests/generic/              # custom generic tests
```

### Style

- **CTE per logical step.** Don't chain 8 transformations into a
  single `SELECT`. Each CTE should have one clear purpose and a
  comment naming the *why*, not the *what*.
- **Lowercase SQL keywords** in dbt models (`select`, `from`,
  `where`). This matches `models/silver/*.sql` and `models/gold/*.sql`
  in this repo.
- **Aliases**: snake_case, descriptive (`valid_sales`, `latest_price`,
  not `t1`, `t2`).
- **Jinja**: prefer `{{ ref('...') }}` and `{{ source('...') }}` over
  hardcoded schema/table names. Use `{{ this }}` for self-references
  in incremental models.
- **`config()` block** at the top of every model with
  `materialized`, `schema`, `incremental_strategy`, and any tags.
  See `models/gold/fct_sales.sql` for the canonical shape.

### Tags

- Silver models carry `tags: ['silver']` (or
  `{{ config(tags=['silver']) }}`).
- Gold models carry `tags: ['gold']`.
- These tags drive selection in `scripts/python/dbt_runner.py`. **A model
  without a tag won't run.**

### Incremental contracts

- All gold models and the silver tables that feed them are
  **incremental with `merge`** strategy.
- Watermark column: `silver_loaded_at` for gold, the collection's own
  timestamp column for silver.
- Lookback: 3 days is the project's standard
  (`lookback_window="3 days"` or equivalent in `is_incremental()`
  logic). Don't shrink this — it catches late-arriving corrections.
- Composite keys (e.g. `fct_sales.sales_key`) must be declared
  explicitly in the `merge` config.

### Tests & docs

- One `schema.yml` per layer (`silver/schema.yml`, `gold/schema.yml`).
- Each model has `description:` and at least:
  - `unique` and `not_null` on its primary key,
  - `relationships` on every foreign key,
  - any business rule as a `dbt_utils.expression_is_true` or custom
    generic test.
- Generic tests live in `museum_dbt/tests/generic/`; one test per
  file, named after the invariant.

### Sources

- Bronze tables are declared once in
  `models/bronze/source.yml`. Reference them via
  `{{ source('bronze', '<table>') }}` — never
  `{{ ref(...) }}` against a bronze-named model.

### Macros

- `museum_dbt/macros/generate_schema.sql` is the custom-schema
  helper. New schema logic goes here, not inline in models.

---

## 6. PowerShell (`scripts/ps1/pipeline_runner.ps1`)

### Style

- **Encoding**: `#Requires -Version 7.0` (or higher) at the top.
  This guarantees `??` null-coalescing and modern error-action
  preferences.
- **Indentation**: 4 spaces. No tabs.
- **Naming**: `PascalCase` for functions and approved verbs
  (`Invoke-BronzeLoad`, `Test-Bronze`, `Start-DbtBuild`),
  `camelCase` for local variables (`$stageName`, `$logFile`).
- **Cmdlets**: prefer native cmdlets (`Get-Date`, `Join-Path`,
  `Test-Path`) over `bash`/`cmd` calls when an equivalent exists.
- **Strings**: double-quoted for interpolation, single-quoted for
  literals.

### Parameters

- All optional behavior is a **named `[switch]` or `[string]`
  parameter** with `[string]$Path` style and a comment block
  describing each. Match the existing flags
  (`-SkipTests`, `-BronzeOnly`, `-FullRefresh`, `-ProjectRoot`).
- Validate early: `Test-Path $ProjectRoot` before doing anything
  expensive; throw a clear `Write-Error` with the offending value.

### Error handling

- `$ErrorActionPreference = 'Stop'` at the top. Treat any non-zero
  exit code from `uv run` as fatal; aggregate failures across
  stages only at the *end*, never mid-run.
- Use `try { ... } catch { ... }` only around stages where a
  partial-success makes sense (e.g. log-file generation). Don't
  wrap the whole script — let the caller see the error.

### Logging & output

- One log file per stage: `logs/<stageName>_<UTC-timestamp>.log`.
- Stream stage stdout to the host terminal **and** to the log file
  via `Tee-Object`. Don't swallow stdout.
- Final summary: a `Format-Table` (or equivalent rich output) with
  `Stage`, `Status`, `Duration`, `LogPath` — one row per stage,
  including failed runs that aborted the chain.

### Portability

- This script runs on Windows PowerShell 7+ and PowerShell Core on
  Linux. Don't use Windows-only APIs (`Add-Type` with WPF, COM
  interop) without an explicit `[CmdletBinding()]` guard.

---

## 7. Git — commits, branches, push

### Branch model

- **`main`** is always deployable. No direct commits except for
  trivial hotfixes coordinated with the maintainer.
- **Feature branches**: `feat/<short-kebab-summary>`
  (`feat/add-museum-hours-aggregate`).
- **Fixes**: `fix/<short-kebab-summary>` (`fix/dbt-runner-flaky-tag`).
- **Docs**: `docs/<short-kebab-summary>`.
- **Chores/refactors**: `chore/<short-kebab-summary>`.
- Branch names are lower-kebab-case, ≤ 60 chars, imperative.

### Commits

- **Conventional Commits** for the subject line:
  `feat(scope): summary`, `fix(scope): summary`,
  `docs(scope): summary`, `chore(scope): summary`,
  `refactor(scope): summary`, `test(scope): summary`.
- **Subject**: ≤ 72 chars, imperative mood
  ("add watermark fallback", not "added" or "adds").
- **Body**: wrap at 72, separated from the subject by a blank line.
  Explain the *why*. Reference the issue/PR id if applicable.
- **Footer**: `BREAKING CHANGE: <details>` if the commit forces a
  schema, env, or runtime change.
- One logical change per commit. If you need `and` in the subject,
  split the commit.

### Commit hygiene for *this* repo

- **Never** commit:
  - `logs/` contents (already gitignored — verify with
    `git status` before staging),
  - `.env` (only `.env.example` / `.env.template` are tracked),
  - generated artifacts (`museum_dbt/target/`, `museum_dbt/dbt_packages/`),
  - notebook checkpoints (`.ipynb_checkpoints/`).
- Before staging, run `git status` and `git diff HEAD` and confirm
  the changes match the task. Don't `git add -A`.
- Stage **only** paths that belong to the change.

### Push

- Push only the branch you intend to open a PR from. Default remote
  is `origin`.
- Force-push (`--force`, `--force-with-lease`) is **not** allowed on
  shared branches. On your own feature branch, prefer
  `--force-with-lease` over `--force`.
- Never push directly to `main`.
- If a hook fails (`pre-commit`, lint, tests), do **not** bypass it
  with `--no-verify`. Fix the underlying problem.

### Pull requests

- PR title mirrors the commit subject (Conventional Commit).
- PR description includes:
  - **Why** — the problem or motivation,
  - **What** — the high-level change,
  - **How to verify** — the exact commands run locally,
  - **Risks** — anything reviewers should pay extra attention to.
- Reference the related issue with `Closes #N` / `Refs #N`.

---

## 8. Comments — when and how

A comment is justified only when one of these is true:

1. **A hidden constraint or contract** — e.g.
   `# Bronze only: _id is the Mongo ObjectId rendered as text.`
2. **A workaround for a specific bug** — e.g.
   `# Airflow 3 parses DAGs out-of-process; this task must not depend
   #  on the scheduler being the parser.`
3. **A non-obvious ordering or invariant** — e.g.
   `# Apply silver merge BEFORE gold; gold depends on silver_loaded_at.`
4. **A link to a design doc** — e.g.
   `# See docs/ARCHITECTURE.md §4 for the watermark rationale.`

A comment is **not** justified when:

- it restates what the code obviously does,
- it narrates the next line ("Now we do X"),
- it's a signpost with no information ("TODO" without context,
  "FIXME" without a path to fix).

### Format

- **Python/docstrings**: triple double-quotes, imperative summary on
  the first line, blank line, then detail.
- **Python/inline**: `#` followed by a single space, sentence case,
  ending with a period when there are multiple sentences.
- **SQL**: `--` with a single space. Block comments (`/* ... */`)
  are reserved for temporarily disabling code.
- **Bash**: `#` with a single space. Header blocks at the top of a
  script describe purpose; inline comments are rare.
- **dbt (Jinja)**: `{# ... #}` for one-liners,
  `{% comment %}{% endcomment %}` for multi-line explanations that
  don't render to SQL.
- **PowerShell**: `#` with a single space. `<# ... #>` for block
  comments when describing a parameter set.

### TODO hygiene

- `TODO:` must include either an owner (`TODO(@nitin): ...`) or a
  linked issue id (`TODO(#123): ...`). A bare `TODO` is not allowed.
- `FIXME` indicates a known bug that must be fixed before the next
  release; remove it as part of the fix commit.

---

## 9. Verification — what to run before declaring done

| Change touches … | Run … |
|---|---|
| `scripts/python/incremental.py` | `uv run scripts/python/incremental.py --dry-run` |
| `scripts/python/dbt_runner.py` | `uv run scripts/python/dbt_runner.py --skip-tests` against a populated warehouse |
| `scripts/python/run_sql_tests.py` | `uv run scripts/python/run_sql_tests.py --layer <layer>` for each affected layer |
| `museum_dbt/models/**` | `uv run scripts/python/dbt_runner.py --full-refresh` |
| `airflow/dags/**` | `docker compose -f docker/compose.yml restart airflow-dag-processor` and watch its log |
| `docker/**` | `docker compose -f docker/compose.yml config -q` (syntax check) |
| `scripts/ps1/pipeline_runner.ps1` | `./scripts/ps1/pipeline_runner.ps1 -BronzeOnly` for a smoke test |
| `scripts/python/**` / `scripts/bash/**` | `./scripts/bash/check_dependencies.sh --strict` then `./scripts/bash/run_pipeline.sh --bronze-only` |
| Any committed change | `git status`, then a clean `git diff HEAD` review |

---

## 10. Pointers — where to look first

| If you're working on … | Start at … |
|---|---|
| Bronze load | `scripts/python/incremental.py`, `docs/ARCHITECTURE.md §4`, `jars/` |
| Silver models | `museum_dbt/models/silver/`, `docs/ARCHITECTURE.md §5` |
| Gold models | `museum_dbt/models/gold/`, `docs/data_catlog.md` |
| Data quality | `scripts/python/run_sql_tests.py`, `museum_dbt/tests/generic/` |
| Orchestration | `airflow/dags/museum_pipeline.py`, `docs/Docker.md` |
| Local runs | `main.py`, `scripts/ps1/pipeline_runner.ps1`, `scripts/bash/run_pipeline.sh` |
| Docker / startup | `docker/compose.yml`, `docker/Dockerfile`, `docs/Docker.md` |
| Pre-flight checks | `scripts/bash/setup_env.sh`, `scripts/bash/check_dependencies.sh`, `scripts/bash/check_jars.sh` |
| Logging / cleanup | `scripts/bash/monitor_logs.sh`, `scripts/bash/clean_logs.sh`, `docs/monitor_logs.md` |
| Real-time repo watching | `monitor.js`, `docs/JS.md` |