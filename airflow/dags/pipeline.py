from airflow import DAG
from airflow.sdk import task
from airflow.providers.smtp.operators.smtp import EmailOperator
from airflow.sdk.timezone import datetime
import pendulum
from datetime import timedelta

from scripts.extraction import extract
from scripts.transformation import transform
from scripts.loading import load

# Timezone configuration
local_tz = pendulum.timezone("Asia/Kolkata")

# Default arguments
default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "email": ["nitin321x@gmail.com"],
}

# Dag definition
with DAG(
    dag_id="ecommerce_etl_pipeline",
    description="E-commerce ETL Pipeline",
    default_args=default_args,
    schedule="0 13 * * MON,WED,FRI",  # 1 PM IST on Mon/Wed/Fri
    start_date=datetime(2024, 1, 1, tzinfo=local_tz),
    catchup=False,
    tags=["etl", "ecommerce", "portfolio"],
) as dag:
    
    # Extract task
    @task(tast_id="extract_data")
    def extract_data():
        from scripts.extraction import extract
        extract.main()

    # Transform task
    @task(task_id="transform_data")
    def transform_data():
        from scripts.transformation import transform
        transform.main()

    # Load Task
    @task(task_id="load_data")
    def load_data():
        from scripts.loading import load
        load.main()

    # Email Notification
    email_notification = EmailOperator(
        task_id="send_email",
        to="nitin321x@gmail.com",
        subject="E-commerce ETL Pipeline Success",
        html_content="""
        <h3>Pipeline Completed Successfully</h3>
        <p>The E-commerce ETL pipeline finished without errors.</p>
        """,
    )

    # Task dependencies
    extract_task = extract_data()
    transform_task = transform_data()
    load_task = load_data()

    extract_task >> transform_task >> load_task >> email_notification