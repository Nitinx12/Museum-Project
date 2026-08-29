{{ config(
    materialized='incremental',
    unique_key=['museum_id', 'day'],
    incremental_strategy='merge',
    on_schema_change='sync_all_columns',
    tags=['silver']
) }}

WITH Source AS (
    SELECT
        NULLIF(TRIM(museum_id::TEXT), '')::NUMERIC::INT AS museum_id,
        CASE TRIM(day)
            WHEN 'Thusday' THEN 'Thursday'
            ELSE TRIM(day)
        END AS day,
        NULLIF(REPLACE(TRIM(open),  ' ', ''), '')::TIME AS open_time,
        NULLIF(REPLACE(TRIM(close), ' ', ''), '')::TIME AS close_time,
        updated_at::TIMESTAMP AS updated_at
    FROM {{ source('bronze', 'museum_hours') }}
    WHERE NULLIF(TRIM(museum_id::TEXT), '') IS NOT NULL
      AND NULLIF(TRIM(day), '') IS NOT NULL
),

Duplicate_check AS (
    SELECT
        *,
        ROW_NUMBER()
            OVER(PARTITION BY museum_id, day
            ORDER BY updated_at DESC NULLS LAST) AS rnk
    FROM Source
),

Incremental_filter AS (
    SELECT *
    FROM Duplicate_check
    {% if is_incremental() %}
    -- This collection has no loaded_at column to fall back on, so a NULL
    -- updated_at is let through every run (rather than being silently and
    -- permanently excluded) until it's fixed upstream.
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
    museum_id,
    day::VARCHAR(10) AS day,
    open_time,
    close_time,
    updated_at,
    CURRENT_TIMESTAMP AS silver_loaded_at
FROM Fixed