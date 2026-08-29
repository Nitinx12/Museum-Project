{{ config(
    materialized='incremental',
    unique_key='work_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Source AS (
    SELECT
        NULLIF(TRIM(work_id::TEXT), '')::NUMERIC::INT   AS work_id,
        TRIM(name)                                 AS name,
        NULLIF(TRIM(artist_id::TEXT), '')::NUMERIC::INT  AS artist_id,
        NULLIF(TRIM(style), '')                    AS style,
        NULLIF(TRIM(museum_id::TEXT), '')::NUMERIC::INT  AS museum_id,
        updated_at::TIMESTAMP AS updated_at
    FROM {{ source('bronze', 'work') }}
    WHERE NULLIF(TRIM(work_id::TEXT), '') IS NOT NULL
),

Duplicate_check AS (
    SELECT
        *,
        ROW_NUMBER()
            OVER(PARTITION BY work_id
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
    name::VARCHAR(150) AS name,
    artist_id,
    style::VARCHAR(50) AS style,
    museum_id,
    updated_at,
    CURRENT_TIMESTAMP AS silver_loaded_at
FROM Fixed