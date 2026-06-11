-- ============================================================
-- Q7 (Mid) | Artwork distribution across canvas size categories
-- Tables  : fct_sales, dim_canvas_size
-- Columns : size_id, work_id, size_category, area_sq_inches
-- ============================================================

SELECT
    dc.size_category,
    COUNT(fs.sales_key)                                             AS artwork_count,
    ROUND(
        COUNT(fs.sales_key) * 100.0 / SUM(COUNT(fs.sales_key)) OVER ()
    , 2)                                                            AS pct_of_total,
    ROUND(MIN(dc.area_sq_inches)::NUMERIC, 2)                       AS min_area_sq_in,
    ROUND(MAX(dc.area_sq_inches)::NUMERIC, 2)                       AS max_area_sq_in,
    ROUND(AVG(dc.area_sq_inches)::NUMERIC, 2)                       AS avg_area_sq_in
FROM gold.fct_sales          fs
JOIN gold.dim_canvas_size    dc ON fs.size_id = dc.size_id
GROUP BY dc.size_category
ORDER BY
    CASE dc.size_category
        WHEN 'Small'       THEN 1
        WHEN 'Medium'      THEN 2
        WHEN 'Large'       THEN 3
        WHEN 'Extra Large' THEN 4
        ELSE 5
    END;