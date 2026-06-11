{{ config(
    materialized='incremental',
    unique_key=['museum_id', 'day'],
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Duplicate_check AS (
    SELECT
        museum_id,
        day,
        open,
        close,
        updated_at,
        ROW_NUMBER()
            OVER(PARTITION BY museum_id, day
            ORDER BY updated_at DESC NULLS LAST) AS rnk
    FROM {{ source('bronze', 'museum_hours') }}
),
Incremental_filter AS (
    SELECT *
    FROM Duplicate_check
    {% if is_incremental() %}
    WHERE updated_at::timestamp >=
    COALESCE(
        (SELECT MAX(updated_at::timestamp) FROM {{ this }}),
        TIMESTAMP '1900-01-01'
    ) - INTERVAL '3 days'
    {% endif %}
),
Fixed AS (
    SELECT *
    FROM Incremental_filter
    WHERE museum_id IS NOT NULL
      AND day IS NOT NULL
      AND rnk = 1
)
SELECT
    NULLIF(TRIM(museum_id), '') :: INT                 AS museum_id,
    CASE TRIM(day)
        WHEN 'Thusday' THEN 'Thursday'
        ELSE TRIM(day)
    END                                     :: VARCHAR(10) AS day,
    NULLIF(REPLACE(TRIM(open),  ' ', ''), '') :: TIME  AS open_time,
    NULLIF(REPLACE(TRIM(close), ' ', ''), '') :: TIME  AS close_time,
    updated_at                  :: TIMESTAMP           AS updated_at,
    CURRENT_TIMESTAMP                                  AS silver_loaded_at
FROM Fixed