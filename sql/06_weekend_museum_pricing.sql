-- ============================================================
-- Q6 (High) | Weekend-open vs weekday-only museum pricing
-- Tests is_open_weekends boolean derivation
-- Tables  : fct_sales, dim_museum
-- Columns : museum_id, sale_price, is_open_weekends, avg_daily_open_hours
-- ============================================================

SELECT
    dm.is_open_weekends,
    COUNT(DISTINCT dm.museum_id)                    AS museum_count,
    COUNT(fs.sales_key)                             AS total_artworks_sold,
    ROUND(AVG(fs.sale_price)::NUMERIC, 2)           AS avg_sale_price,
    ROUND(AVG(fs.regular_price)::NUMERIC, 2)        AS avg_regular_price,
    ROUND(AVG(fs.discount_pct)::NUMERIC, 2)         AS avg_discount_pct,
    ROUND(AVG(dm.avg_daily_open_hours)::NUMERIC, 2) AS avg_open_hours
FROM gold.fct_sales      fs
JOIN gold.dim_museum     dm ON fs.museum_id = dm.museum_id
WHERE fs.is_in_museum = TRUE
  AND dm.is_open_weekends IS NOT NULL          -- exclude museums with no hours data
GROUP BY dm.is_open_weekends
ORDER BY dm.is_open_weekends DESC;