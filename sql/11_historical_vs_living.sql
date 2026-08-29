-- ============================================================
-- Q11 · Historical vs Living Artist: Pricing & Discount Deep-Dive
-- Joins : fct_sales → dim_artist
-- Difficulty : Mid-High
-- ============================================================
-- PURPOSE
--   Compare pricing dynamics between artists flagged as 'Historical'
--   (death_year IS NOT NULL) and 'Living / Unknown'.  Historical
--   works often command premiums; this tests whether discount_pct
--   reflects that asymmetry.
--
-- OUTPUT COLUMNS
--   artist_status           – Historical / Living / Unknown
--   era                     – within each status, break by era
--   artist_count
--   artwork_count
--   sku_count
--   avg_sale_price
--   median_sale_price       – using PERCENTILE_CONT
--   avg_regular_price
--   avg_discount_pct
--   pct_zero_discount       – fraction of SKUs with 0% or NULL discount
--   price_premium_ratio     – avg_sale_price / overall avg (>1 = premium)
-- ============================================================

WITH overall_avg AS (
    SELECT AVG(sale_price) AS global_avg FROM gold.fct_sales
)
SELECT
    da.artist_status,
    da.era,
    COUNT(DISTINCT da.artist_id)                                       AS artist_count,
    COUNT(DISTINCT fs.work_id)                                         AS artwork_count,
    COUNT(*)                                                           AS sku_count,
    ROUND(AVG(fs.sale_price)::NUMERIC,  2)                             AS avg_sale_price,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fs.sale_price)
        ::NUMERIC, 2
    )                                                                  AS median_sale_price,
    ROUND(AVG(fs.regular_price)::NUMERIC,2)                            AS avg_regular_price,
    ROUND(AVG(fs.discount_pct)::NUMERIC, 2)                            AS avg_discount_pct,
    ROUND(
        100.0 * SUM(CASE WHEN COALESCE(fs.discount_pct, 0) = 0 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0),
    2)                                                                 AS pct_zero_discount,
    ROUND(
        (AVG(fs.sale_price) / NULLIF((SELECT global_avg FROM overall_avg), 0))
        ::NUMERIC, 4
    )                                                                  AS price_premium_ratio
FROM gold.fct_sales  fs
JOIN gold.dim_artist da ON fs.artist_id = da.artist_id
GROUP BY da.artist_status, da.era
ORDER BY da.artist_status, avg_sale_price DESC NULLS LAST;