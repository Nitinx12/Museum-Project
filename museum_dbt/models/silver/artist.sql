{{ config(
    materialized='incremental',
    unique_key='artist_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns',
    tags=['silver']
) }}

WITH Source AS (
    SELECT
        NULLIF(TRIM(artist_id::TEXT), '')::NUMERIC::INT AS artist_id,
        NULLIF(TRIM(first_name), '')   AS first_name,
        NULLIF(TRIM(middle_names), '') AS middle_names,
        NULLIF(TRIM(last_name), '')    AS last_name,
        TRIM(nationality)              AS nationality,
        TRIM(style)                    AS style,
        NULLIF(TRIM(birth::TEXT), '')::INT   AS birth,
        NULLIF(TRIM(death::TEXT), '')::INT   AS death,
        updated_at::TIMESTAMP AS updated_at
    FROM {{ source('bronze', 'artist') }}
    WHERE NULLIF(TRIM(artist_id::TEXT), '') IS NOT NULL
),

Duplicate_check AS (
    SELECT
        *,
        ROW_NUMBER()
            OVER(PARTITION BY artist_id
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
    artist_id,
    TRIM(
        CONCAT_WS(
            ' ',
            first_name,
            middle_names,
            last_name
        )
    )::VARCHAR(75)           AS artist_name,
    nationality::VARCHAR(50) AS nationality,
    style::VARCHAR(50)       AS style,
    birth                    AS birth_year,
    death                    AS death_year,
    updated_at,
    CURRENT_TIMESTAMP AS silver_loaded_at
FROM Fixed