-- ============================================================
-- Q5 (Mid) | Artworks with 'Unknown' subject_tags on sale
-- Validates COALESCE fallback in dim_artwork
-- Tables  : fct_sales, dim_artwork
-- Columns : work_id, sale_price, is_in_museum, subject_tags
-- ============================================================

-- Summary count
SELECT
    daw.subject_tags,
    COUNT(fs.sales_key)                         AS total_records,
    COUNT(CASE WHEN fs.is_in_museum THEN 1 END) AS in_museum_count,
    ROUND(AVG(fs.sale_price)::NUMERIC, 2)       AS avg_sale_price,
    ROUND(MIN(fs.sale_price)::NUMERIC, 2)       AS min_sale_price,
    ROUND(MAX(fs.sale_price)::NUMERIC, 2)       AS max_sale_price
FROM gold.fct_sales      fs
JOIN gold.dim_artwork    daw ON fs.work_id = daw.work_id
WHERE daw.subject_tags = 'Unknown'
GROUP BY daw.subject_tags;