{{ config(
    materialized='incremental',
    unique_key=['work_id', 'subject'],
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Source AS (
    SELECT
        NULLIF(TRIM(work_id::TEXT), '')::NUMERIC::INT AS work_id,
        NULLIF(TRIM(subject), '') AS subject,
        updated_at::TIMESTAMP AS updated_at
    FROM {{ source('bronze', 'subject') }}
    WHERE NULLIF(TRIM(work_id::TEXT), '') IS NOT NULL
      AND NULLIF(TRIM(subject), '') IS NOT NULL
),

Duplicate_check AS (
    SELECT
        *,
        ROW_NUMBER()
            OVER(PARTITION BY work_id, subject
            ORDER BY updated_at DESC NULLS LAST) AS rnk
    FROM Source
),

Incremental_filter AS (
    SELECT *
    FROM Duplicate_check
    {% if is_incremental() %}
    WHERE updated_at IS NULL
       OR updated_at >=
        COALESCE(
            (SELECT MAX(updated_at) FROM {{ this }}),
            TIMESTAMP '1900-01-01'
        ) - INTERVAL '3 days'
    {% endif %}
),

Fixed AS (
    SELECT *
    FROM Incremental_filter
    WHERE rnk = 1
)

SELECT
    work_id,
    subject::VARCHAR(100) AS subject,
    updated_at,
    CURRENT_TIMESTAMP AS silver_loaded_at
FROM Fixed