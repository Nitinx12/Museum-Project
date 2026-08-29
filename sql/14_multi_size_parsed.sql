-- ============================================================
-- Q14 · Multi-Size Artworks: Price Spread & Upsell Opportunity
-- Joins : fct_sales → dim_artwork → dim_canvas_size → dim_artist
-- Difficulty : High
-- ============================================================
-- PURPOSE
--   For artworks available in 3+ size variants, analyse the price
--   spread between their smallest and largest canvas option.  A
--   high spread implies strong upsell potential.  Validates that
--   the fct_sales dedup (ROW_NUMBER) left the correct latest record
--   per (work_id, size_id).
--
-- OUTPUT COLUMNS
--   work_id, artwork_name, style (artwork)
--   artist_name, era, nationality
--   size_variant_count       – distinct size_ids
--   min_sale_price           – cheapest size
--   max_sale_price           – most expensive size
--   price_spread             – max - min
--   price_spread_ratio       – max / min  (upsell multiplier)
--   size_categories_present  – comma-list of distinct size categories
--   avg_discount_pct
-- ============================================================

WITH artwork_sizes AS (
    SELECT
        fs.work_id,
        COUNT(DISTINCT fs.size_id)                                        AS size_variant_count,
        MIN(fs.sale_price)                                                AS min_sale_price,
        MAX(fs.sale_price)                                                AS max_sale_price,
        AVG(fs.discount_pct)                                              AS avg_discount_pct,
        STRING_AGG(DISTINCT cs.size_category, ',' ORDER BY cs.size_category)
                                                                          AS size_categories_present
    FROM gold.fct_sales        fs
    JOIN gold.dim_canvas_size  cs ON fs.size_id = cs.size_id
    GROUP BY fs.work_id
    HAVING COUNT(DISTINCT fs.size_id) >= 3
)
SELECT
    a.size_variant_count,
    aw.work_id,
    aw.artwork_name,
    aw.style,
    da.artist_name,
    da.era,
    da.nationality,
    ROUND(a.min_sale_price::NUMERIC,  2)                                 AS min_sale_price,
    ROUND(a.max_sale_price::NUMERIC,  2)                                 AS max_sale_price,
    ROUND((a.max_sale_price - a.min_sale_price)::NUMERIC, 2)             AS price_spread,
    ROUND((a.max_sale_price / NULLIF(a.min_sale_price, 0))::NUMERIC, 2) AS price_spread_ratio,
    a.size_categories_present,
    ROUND(a.avg_discount_pct::NUMERIC, 2)                                AS avg_discount_pct
FROM artwork_sizes   a
JOIN gold.dim_artwork     aw ON a.work_id = aw.work_id
JOIN gold.dim_artist      da ON aw.artist_id = da.artist_id
ORDER BY price_spread_ratio DESC NULLS LAST
LIMIT 25;