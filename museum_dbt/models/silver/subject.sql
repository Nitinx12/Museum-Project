{{ config(
    materialized='incremental',
    unique_key=['work_id', 'subject'],
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Duplicate_check AS (
    SELECT
        work_id,
        subject,
        loaded_at,
        updated_at,
        ROW_NUMBER()
            OVER(PARTITION BY work_id, subject
            ORDER BY updated_at DESC NULLS LAST) AS rnk
    FROM {{ source('bronze', 'subject') }}
),
Incremental_filter AS (
    SELECT *
    FROM Duplicate_check
    {% if is_incremental() %}
    WHERE COALESCE(updated_at, loaded_at)::timestamp >= 
		COALESCE(
			(SELECT MAX(updated_at::timestamp) FROM {{ this }}),
			TIMESTAMP '1900-01-01'
		) - INTERVAL '3 days'
    {% endif %}
),
Fixed AS (
    SELECT *
    FROM Incremental_filter
    WHERE work_id IS NOT NULL
      AND TRIM(work_id)  != ''
      AND subject IS NOT NULL
      AND TRIM(subject) != ''
      AND rnk = 1
)
SELECT
    NULLIF(TRIM(work_id), '') :: NUMERIC :: INT  AS work_id,
    TRIM(subject)             :: VARCHAR(100)    AS subject,
    updated_at                :: TIMESTAMP       AS updated_at,
    loaded_at                 :: TIMESTAMP       AS loaded_at,
    CURRENT_TIMESTAMP                            AS silver_loaded_at
FROM Fixed