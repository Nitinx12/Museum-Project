-- ============================================================
-- Q2 (High) | Canvas size category → revenue & discount
-- Which size category drives highest revenue?
-- Tables  : fct_sales, dim_canvas_size
-- Columns : size_id, sale_price, regular_price, discount_pct,
--           size_category, area_sq_inches
-- ============================================================

SELECT
    dc.size_category,
    COUNT(fs.sales_key)                             AS total_artworks,
    ROUND(SUM(fs.sale_price)::NUMERIC, 2)           AS total_revenue,
    ROUND(AVG(fs.sale_price)::NUMERIC, 2)           AS avg_sale_price,
    ROUND(AVG(fs.regular_price)::NUMERIC, 2)        AS avg_regular_price,
    ROUND(AVG(fs.discount_pct)::NUMERIC, 2)         AS avg_discount_pct,
    ROUND(AVG(dc.area_sq_inches)::NUMERIC, 2)       AS avg_area_sq_inches
FROM gold.fct_sales          fs
JOIN gold.dim_canvas_size    dc ON fs.size_id = dc.size_id
GROUP BY dc.size_category
ORDER BY total_revenue DESC;
