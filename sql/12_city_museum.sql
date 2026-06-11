-- ============================================================
-- Q12 · City-Level Museum & Artwork Analysis
-- Joins : fct_sales → dim_museum
-- Difficulty : Mid
-- ============================================================
-- PURPOSE
--   Aggregate museum metrics at the city level to identify which
--   cities concentrate the most art supply and what their overall
--   pricing and discount profile looks like.
--
-- OUTPUT COLUMNS
--   country
--   city
--   museum_count            – distinct museums in city
--   total_artworks          – distinct work_ids
--   total_sku_rows
--   total_sale_revenue
--   avg_sale_price
--   avg_discount_pct
--   avg_opening_days        – avg opening_days_per_week across city museums
--   pct_weekend_museums     – % of city museums open on weekends
--   city_revenue_rank       – ranked by total_sale_revenue within country
-- ============================================================

WITH city_agg AS (
    SELECT
        dm.country,
        dm.city,
        COUNT(DISTINCT dm.museum_id)                                     AS museum_count,
        COUNT(DISTINCT fs.work_id)                                       AS total_artworks,
        COUNT(*)                                                         AS total_sku_rows,
        SUM(fs.sale_price)                                               AS total_sale_revenue,
        AVG(fs.sale_price)                                               AS avg_sale_price,
        AVG(fs.discount_pct)                                             AS avg_discount_pct,
        AVG(dm.opening_days_per_week)                                    AS avg_opening_days,
        100.0 * SUM(CASE WHEN dm.is_open_weekends IS TRUE THEN 1 ELSE 0 END)
              / NULLIF(COUNT(DISTINCT dm.museum_id), 0)                  AS pct_weekend_museums
    FROM gold.fct_sales  fs
    JOIN gold.dim_museum dm ON fs.museum_id = dm.museum_id
    GROUP BY dm.country, dm.city
)
SELECT
    country,
    city,
    museum_count,
    total_artworks,
    total_sku_rows,
    ROUND(total_sale_revenue::NUMERIC, 2)   AS total_sale_revenue,
    ROUND(avg_sale_price::NUMERIC,     2)   AS avg_sale_price,
    ROUND(avg_discount_pct::NUMERIC,   2)   AS avg_discount_pct,
    ROUND(avg_opening_days::NUMERIC,   2)   AS avg_opening_days,
    ROUND(pct_weekend_museums::NUMERIC,2)   AS pct_weekend_museums,
    RANK() OVER (
        PARTITION BY country
        ORDER BY total_sale_revenue DESC NULLS LAST
    )                                       AS city_revenue_rank
FROM city_agg
ORDER BY total_sale_revenue DESC NULLS LAST;