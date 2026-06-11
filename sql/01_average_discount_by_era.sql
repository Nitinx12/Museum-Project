-- ============================================================
-- Q1 (Mid) | Average discount % per artist era
-- Which era offers the steepest discounts?
-- Tables  : fct_sales, dim_artist
-- Columns : artist_id, discount_pct, era
-- ============================================================

SELECT
    da.era,
    COUNT(fs.sales_key)                         AS total_artworks,
    ROUND(AVG(fs.discount_pct)::NUMERIC, 2)     AS avg_discount_pct,
    ROUND(MIN(fs.discount_pct)::NUMERIC, 2)     AS min_discount_pct,
    ROUND(MAX(fs.discount_pct)::NUMERIC, 2)     AS max_discount_pct
FROM gold.fct_sales      fs
JOIN gold.dim_artist     da ON fs.artist_id = da.artist_id
WHERE fs.discount_pct IS NOT NULL
GROUP BY da.era
ORDER BY avg_discount_pct DESC;