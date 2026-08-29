{{ config(
    materialized='incremental',
    unique_key='museum_id',
    incremental_strategy='merge',
    on_schema_change='append_new_columns',
    tags=['gold', 'dimension']
) }}

{% if is_incremental() %}
-- Hours stats are an aggregate across a museum's full week of hours rows,
-- so a museum is "changed" if EITHER its own row changed OR any of its
-- hours rows changed. Collect the affected museum_ids here, then
-- recompute each one's stats from its FULL set of hours rows below.
WITH changed_museum_ids AS (
    SELECT museum_id FROM {{ ref('museum') }}
    WHERE silver_loaded_at > (
        COALESCE((SELECT MAX(silver_loaded_at) FROM {{ this }}), TIMESTAMP '1900-01-01')
        - INTERVAL '3 days'
    )
    UNION
    SELECT museum_id FROM {{ ref('museum_hours') }}
    WHERE silver_loaded_at > (
        COALESCE((SELECT MAX(silver_loaded_at) FROM {{ this }}), TIMESTAMP '1900-01-01')
        - INTERVAL '3 days'
    )
),
{% else %}
WITH
{% endif %}

museum AS (
    SELECT
        museum_id,
        museum_name,
        city,
        state,
        country,
        address,
        phone,
        url,
        silver_loaded_at
    FROM {{ ref('museum') }}
    WHERE museum_id IS NOT NULL
    {% if is_incremental() %}
      AND museum_id IN (SELECT museum_id FROM changed_museum_ids)
    {% endif %}
),

hours_stats AS (
    SELECT
        museum_id,

        -- How many days per week the museum is open
        COUNT(*)                                                   AS opening_days_per_week,

        -- Average daily open hours (close - open in fractional hours)
        ROUND(
            AVG(
                EXTRACT(EPOCH FROM (close_time - open_time)) / 3600.0
            )::NUMERIC, 2
        )                                                          AS avg_daily_open_hours,

        -- Earliest opening time across the week
        MIN(open_time)                                             AS earliest_open_time,

        -- Latest closing time across the week
        MAX(close_time)                                            AS latest_close_time,

        -- Is the museum open on weekends?
        MAX(CASE WHEN day IN ('Saturday', 'Sunday') THEN 1 ELSE 0 END) AS is_open_weekends

    FROM {{ ref('museum_hours') }}
    WHERE open_time  IS NOT NULL
      AND close_time IS NOT NULL
    {% if is_incremental() %}
      AND museum_id IN (SELECT museum_id FROM changed_museum_ids)
    {% endif %}
    GROUP BY museum_id
)

SELECT
    m.museum_id,
    m.museum_name,
    COALESCE(m.city, 'Unknown')                     AS city,
    m.state,
    COALESCE(m.country, 'Unknown')                  AS country,
    NULLIF(REGEXP_REPLACE(TRIM(m.address), '\s+', ' ', 'g'), '') AS address,
    NULLIF(REGEXP_REPLACE(TRIM(m.phone), '\s+', ' ', 'g'), '')   AS phone,
    NULLIF(REGEXP_REPLACE(TRIM(m.url), '\s+', ' ', 'g'), '')     AS url,

    -- Hours enrichment (NULL-safe for museums with no hours loaded)
    COALESCE(h.opening_days_per_week, 0)            AS opening_days_per_week,
    h.avg_daily_open_hours,
    h.earliest_open_time,
    h.latest_close_time,
    CASE
        WHEN h.is_open_weekends = 1 THEN TRUE
        WHEN h.museum_id IS NULL    THEN NULL
        ELSE FALSE
    END                                             AS is_open_weekends,

    m.silver_loaded_at,
    CURRENT_TIMESTAMP AS gold_loaded_at

FROM museum     m
LEFT JOIN hours_stats h ON m.museum_id = h.museum_id