"""
scripts/python/generate_quality_report.py
=======================================
Generates a human-readable HTML report of data quality and pipeline health.
It aggregates data from:
1. bronze.etl_logs: Load statistics and validation status.
2. museum_dbt/target/run_results.json: dbt test results.
"""

from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from utils.engine import postgres_engine
from utils.logging_config import get_logger

log = get_logger("museum.reporting.quality")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = PROJECT_ROOT / "reports"
DBT_RESULTS_FILE = PROJECT_ROOT / "museum_dbt" / "target" / "run_results.json"

def fetch_load_stats(engine: Engine) -> list[dict]:
    """Fetch the most recent run statistics for each collection from bronze.etl_logs."""
    query = text("""
        SELECT DISTINCT ON (table_name)
            table_name,
            started_at,
            status,
            validation_status,
            mongo_rows,
            rows_inserted,
            rows_updated,
            error
        FROM bronze.etl_logs
        ORDER BY table_name, started_at DESC
    """)
    with engine.connect() as conn:
        result = conn.execute(query)
        return [dict(row._mapping) for row in result]

def fetch_dbt_stats() -> dict:
    """Parse dbt's run_results.json to find the status of the latest tests."""
    if not DBT_RESULTS_FILE.exists():
        return {"error": "dbt run_results.json not found. Run dbt test first."}

    with open(DBT_RESULTS_FILE, "r") as f:
        data = json.load(f)

    results = data.get("results", [])
    passed = 0
    failed = 0
    total = 0

    for r in results:
        status = r.get("status")
        if status == "success":
            passed += 1
        elif status == "fail":
            failed += 1
        total += 1

    return {"passed": passed, "failed": failed, "total": total}

def generate_html_report(load_stats: list[dict], dbt_stats: dict) -> str:
    """Convert the statistics into a clean HTML document."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Load stats table
    load_rows = ""
    for s in load_stats:
        status_color = "green" if s["status"] == "OK" else "red"
        val_color = "green" if s["validation_status"] == "PASS" else "red"
        load_rows += f"""
        <tr>
            <td>{s['table_name']}</td>
            <td>{s['started_at']}</td>
            <td style="color: {status_color}; font-weight: bold;">{s['status']}</td>
            <td style="color: {val_color}; font-weight: bold;">{s['validation_status']}</td>
            <td>{s['mongo_rows']:,}</td>
            <td>{s['rows_inserted']:,}</td>
            <td>{s['rows_updated']:,}</td>
            <td>{s['error'] or '-'}</td>
        </tr>
        """

    # DBT stats summary
    dbt_html = ""
    if "error" in dbt_stats:
        dbt_html = f"<p style='color: red;'>{dbt_stats['error']}</p>"
    else:
        dbt_html = f"""
        <div style='display: flex; gap: 20px;'>
            <div style='background: #e8f5e9; padding: 15px; border-radius: 8px; border: 1px solid #2e7d32;'>
                <strong>Passed Tests:</strong> {dbt_stats['passed']}
            </div>
            <div style='background: #ffebee; padding: 15px; border-radius: 8px; border: 1px solid #c62828;'>
                <strong>Failed Tests:</strong> {dbt_stats['failed']}
            </div>
            <div style='background: #f5f5f5; padding: 15px; border-radius: 8px; border: 1px solid #9e9e9e;'>
                <strong>Total Tests:</strong> {dbt_stats['total']}
            </div>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Museum ETL Quality Report</title>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 40px; color: #333; line-height: 1.6; }}
            h1 {{ color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
            h2 {{ color: #34495e; margin-top: 30px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #f8f9fa; color: #666; text-transform: uppercase; font-size: 0.85em; }}
            tr:hover {{ background-color: #f5f5f5; }}
            .timestamp {{ color: #888; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <h1>Museum ETL Data Quality Report</h1>
        <p class="timestamp">Generated on: {now}</p>

        <h2>1. Pipeline Load Health (Bronze Layer)</h2>
        <table>
            <thead>
                <tr>
                    <th>Collection</th>
                    <th>Last Run</th>
                    <th>Status</th>
                    <th>Validation</th>
                    <th>Mongo Rows</th>
                    <th>Inserted</th>
                    <th>Updated</th>
                    <th>Error</th>
                </tr>
            </thead>
            <tbody>
                {load_rows}
            </tbody>
        </table>

        <h2>2. Transformation Quality (dbt Tests)</h2>
        {dbt_html}
    </body>
    </html>
    """

def main():
    REPORT_DIR.mkdir(exist_ok=True)
    engine = postgres_engine()

    try:
        log.info("Generating data quality report...")
        load_stats = fetch_load_stats(engine)
        dbt_stats = fetch_dbt_stats()

        html_content = generate_html_report(load_stats, dbt_stats)

        report_path = REPORT_DIR / "quality_report.html"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        log.info(f"Report successfully generated at: {report_path}")
        print(f"Successfully generated report: {report_path}")

    finally:
        engine.dispose()

if __name__ == "__main__":
    main()
