{{ config(
    materialized='incremental',
    unique_key='museum_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Duplicate_check AS (
    SELECT
        museum_id,
        name,
        city,
        state,
        postal,
        country,
        address,
        phone,
        url,
        loaded_at,
        updated_at,
        ROW_NUMBER()
            OVER(PARTITION BY museum_id
            ORDER BY updated_at DESC NULLS LAST) AS rnk
    FROM {{ source('bronze', 'museum') }}
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
    WHERE museum_id IS NOT NULL
      AND TRIM(museum_id) != ''
      AND rnk = 1
),
Cleaned AS (
    SELECT
        museum_id,
        name,
        country,
        address,
        phone,
        url,
        loaded_at,
        updated_at,

        -- Fix 1: city is purely numeric (postal landed in city, real city is in state)
        -- Fix 2: city has merged postal+city e.g. "6731 AW Otterlo"
        CASE
            WHEN TRIM(city) ~ '^[0-9]+$'
             AND NULLIF(TRIM(state), '') IS NOT NULL
                THEN TRIM(state)
            WHEN TRIM(city) ~ '^[0-9]+\s+[A-Z]{2}\s+\S'
                THEN TRIM(REGEXP_REPLACE(TRIM(city), '^[0-9]+\s+[A-Z]{2}\s+', ''))
            ELSE TRIM(city)
        END AS city,

        -- state: clear it when it was actually holding the city name
        CASE
            WHEN TRIM(city) ~ '^[0-9]+$'
             AND NULLIF(TRIM(state), '') IS NOT NULL
                THEN NULL
            ELSE NULLIF(TRIM(state), '')
        END AS state,

        -- postal: rescue from city when swapped; extract from merged field; else keep as-is
        CASE
            WHEN TRIM(city) ~ '^[0-9]+$'
             AND NULLIF(TRIM(postal), '') IS NULL
                THEN TRIM(city)
            WHEN TRIM(city) ~ '^[0-9]+\s+[A-Z]{2}\s+\S'
                THEN TRIM(REGEXP_REPLACE(TRIM(city), '\s+\S+$', ''))
            ELSE NULLIF(TRIM(postal), '')
        END AS postal

    FROM Fixed
)
SELECT
    NULLIF(TRIM(museum_id), '') :: INT          AS museum_id,
    TRIM(name)                  :: VARCHAR(100) AS museum_name,
    city                        :: VARCHAR(50)  AS city,
    state                       :: VARCHAR(50)  AS state,
    postal                      :: VARCHAR(20)  AS postal,
    TRIM(country)               :: VARCHAR(50)  AS country,
    TRIM(address)               :: VARCHAR(150) AS address,
    NULLIF(TRIM(phone), '')     :: VARCHAR(30)  AS phone,
    NULLIF(TRIM(url), '')       :: VARCHAR(200) AS url,
    updated_at                  :: TIMESTAMP    AS updated_at,
    loaded_at                   :: TIMESTAMP    AS loaded_at,
    CURRENT_TIMESTAMP                           AS silver_loaded_at
FROM Cleaned