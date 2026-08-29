{{ config(
    materialized='incremental',
    unique_key='size_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Source AS (
    SELECT
        NULLIF(TRIM(size_id::TEXT), '')::NUMERIC::INT AS size_id,
        NULLIF(TRIM(width::TEXT), '')::INT  AS width_inches,
        NULLIF(TRIM(height::TEXT), '')::INT AS height_inches,
        TRIM(label) AS label,
        updated_at::TIMESTAMP AS updated_at
    FROM {{ source('bronze', 'canvas_size') }}
    WHERE NULLIF(TRIM(size_id::TEXT), '') IS NOT NULL
),

Duplicate_check AS (
    SELECT
        *,
        ROW_NUMBER()
            OVER(PARTITION BY size_id
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
    size_id,
    width_inches,
    height_inches,
    label::VARCHAR(100) AS label,
    updated_at,
    CURRENT_TIMESTAMP AS silver_loaded_at
FROM Fixed