-- ============================================================
-- Q3 (Mid) | Museum artwork count vs opening hours
-- Do top museums stay open longer?
-- Tables  : fct_sales, dim_museum
-- Columns : museum_id, work_id, museum_name,
--           avg_daily_open_hours, opening_days_per_week
-- ============================================================

SELECT
    dm.museum_name,
    dm.city,
    dm.country,
    COUNT(DISTINCT fs.work_id)                      AS total_artworks,
    dm.opening_days_per_week,
    dm.avg_daily_open_hours,
    dm.earliest_open_time,
    dm.latest_close_time
FROM gold.fct_sales      fs
JOIN gold.dim_museum     dm ON fs.museum_id = dm.museum_id
WHERE fs.is_in_museum = TRUE
GROUP BY
    dm.museum_name, dm.city, dm.country,
    dm.opening_days_per_week, dm.avg_daily_open_hours,
    dm.earliest_open_time, dm.latest_close_time
ORDER BY total_artworks DESC
LIMIT 20;