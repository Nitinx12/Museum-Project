-- ============================================================
-- Q18 · Museum Operating Hours vs Artwork Richness Correlation
-- Joins : fct_sales → dim_museum
-- Difficulty : Mid-High
-- ============================================================
-- PURPOSE
--   Test whether museums with longer opening hours tend to hold
--   more artworks and command higher sale prices.  Uses bucketed
--   open-hours ranges for BI-friendly grouping.
--
-- OUTPUT COLUMNS
--   hours_bucket           – daily open-hours range (e.g. '6-8 hrs')
--   museum_count
--   avg_daily_open_hours
--   avg_opening_days_per_week
--   pct_weekend_museums
--   total_artworks
--   avg_artworks_per_museum
--   avg_sale_price
--   avg_discount_pct
--   total_revenue
-- ============================================================

WITH museum_metrics AS (
    SELECT
        dm.museum_id,
        dm.avg_daily_open_hours,
        dm.opening_days_per_week,
        dm.is_open_weekends,
        CASE
            WHEN dm.avg_daily_open_hours IS NULL         THEN 'Unknown'
            WHEN dm.avg_daily_open_hours < 6             THEN '< 6 hrs'
            WHEN dm.avg_daily_open_hours BETWEEN 6 AND 8 THEN '6–8 hrs'
            WHEN dm.avg_daily_open_hours BETWEEN 8 AND 10 THEN '8–10 hrs'
            ELSE                                              '10+ hrs'
        END                                              AS hours_bucket,
        COUNT(DISTINCT fs.work_id)                       AS artworks_in_museum,
        COUNT(*)                                         AS sku_rows,
        AVG(fs.sale_price)                               AS avg_sale_price,
        AVG(fs.discount_pct)                             AS avg_discount_pct,
        SUM(fs.sale_price)                               AS total_revenue
    FROM gold.fct_sales  fs
    JOIN gold.dim_museum dm ON fs.museum_id = dm.museum_id
    GROUP BY
        dm.museum_id, dm.avg_daily_open_hours,
        dm.opening_days_per_week, dm.is_open_weekends, hours_bucket
)
SELECT
    hours_bucket,
    COUNT(DISTINCT museum_id)                               AS museum_count,
    ROUND(AVG(avg_daily_open_hours)::NUMERIC,     2)        AS avg_daily_open_hours,
    ROUND(AVG(opening_days_per_week)::NUMERIC,    2)        AS avg_opening_days_per_week,
    ROUND(
        100.0 * SUM(CASE WHEN is_open_weekends IS TRUE THEN 1 ELSE 0 END)
        / NULLIF(COUNT(DISTINCT museum_id), 0),
    2)                                                      AS pct_weekend_museums,
    SUM(artworks_in_museum)                                 AS total_artworks,
    ROUND(AVG(artworks_in_museum)::NUMERIC,       2)        AS avg_artworks_per_museum,
    ROUND(AVG(avg_sale_price)::NUMERIC,           2)        AS avg_sale_price,
    ROUND(AVG(avg_discount_pct)::NUMERIC,         2)        AS avg_discount_pct,
    ROUND(SUM(total_revenue)::NUMERIC,            2)        AS total_revenue
FROM museum_metrics
GROUP BY hours_bucket
ORDER BY
    CASE hours_bucket
        WHEN '< 6 hrs'  THEN 1
        WHEN '6–8 hrs'  THEN 2
        WHEN '8–10 hrs' THEN 3
        WHEN '10+ hrs'  THEN 4
        ELSE 5
    END;