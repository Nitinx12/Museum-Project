{{ config(
    materialized='table',
    tags=['gold', 'dimension']
) }}

WITH museum AS (
    SELECT
        museum_id,
        museum_name,
        city,
        state,
        country,
        address,
        phone,
        url
    FROM {{ ref('museum') }}
    WHERE museum_id IS NOT NULL
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
    GROUP BY museum_id
)

SELECT
    m.museum_id,
    m.museum_name,
    COALESCE(m.city, 'Unknown')                     AS city,
    m.state,
    COALESCE(m.country, 'Unknown')                  AS country,
    m.address,
    m.phone,
    m.url,

    -- Hours enrichment (NULL-safe for museums with no hours loaded)
    COALESCE(h.opening_days_per_week, 0)            AS opening_days_per_week,
    h.avg_daily_open_hours,
    h.earliest_open_time,
    h.latest_close_time,
    CASE
        WHEN h.is_open_weekends = 1 THEN TRUE
        WHEN h.museum_id IS NULL    THEN NULL
        ELSE FALSE
    END                                             AS is_open_weekends

FROM museum     m
LEFT JOIN hours_stats h ON m.museum_id = h.museum_id