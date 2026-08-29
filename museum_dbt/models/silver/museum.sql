{{ config(
    materialized='incremental',
    unique_key='museum_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Source AS (
    SELECT
        NULLIF(TRIM(museum_id::TEXT), '')::NUMERIC::INT AS museum_id,
        TRIM(name)               AS name,
        TRIM(city)                AS city,
        NULLIF(TRIM(state), '')   AS state,
        NULLIF(TRIM(postal), '')  AS postal,
        TRIM(country)             AS country,
        TRIM(address)             AS address,
        NULLIF(TRIM(phone), '')   AS phone,
        NULLIF(TRIM(url), '')     AS url,
        updated_at::TIMESTAMP AS updated_at
    FROM {{ source('bronze', 'museum') }}
    WHERE NULLIF(TRIM(museum_id::TEXT), '') IS NOT NULL
),

Duplicate_check AS (
    SELECT
        *,
        ROW_NUMBER()
            OVER(PARTITION BY museum_id
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
),

Cleaned AS (
    SELECT
        museum_id,
        name,
        country,
        address,
        phone,
        url,
        updated_at,

        -- Fix 1: city is purely numeric (postal landed in city) and the real
        --        city name landed in "state" -> recover it from there.
        -- Fix 2: city has merged postal+city, e.g. "6731 AW Otterlo".
        -- Fix 3: city is purely numeric with NO state to recover a name from
        --        -> there's nothing usable to put in city, so NULL it rather
        --        than leaving a postal code masquerading as a city name.
        CASE
            WHEN city ~ '^[0-9]+$' AND state IS NOT NULL
                THEN state
            WHEN city ~ '^[0-9]+$'
                THEN NULL
            WHEN city ~ '^[0-9]+\s+[A-Z]{2}\s+\S'
                THEN TRIM(REGEXP_REPLACE(city, '^[0-9]+\s+[A-Z]{2}\s+', ''))
            ELSE city
        END AS city,

        -- state: clear it when it was actually holding the city name
        CASE
            WHEN city ~ '^[0-9]+$' AND state IS NOT NULL
                THEN NULL
            ELSE state
        END AS state,

        -- postal: rescue from city when swapped; extract from merged field; else keep as-is
        CASE
            WHEN city ~ '^[0-9]+$' AND postal IS NULL
                THEN city
            WHEN city ~ '^[0-9]+\s+[A-Z]{2}\s+\S'
                THEN TRIM(REGEXP_REPLACE(city, '\s+\S+$', ''))
            ELSE postal
        END AS postal

    FROM Fixed
)

SELECT
    museum_id,
    name::VARCHAR(100)    AS museum_name,
    city::VARCHAR(50)     AS city,
    state::VARCHAR(50)    AS state,
    postal::VARCHAR(20)   AS postal,
    country::VARCHAR(50)  AS country,
    address::VARCHAR(150) AS address,
    phone::VARCHAR(30)    AS phone,
    url::VARCHAR(200)     AS url,
    updated_at,
    CURRENT_TIMESTAMP AS silver_loaded_at
FROM Cleaned