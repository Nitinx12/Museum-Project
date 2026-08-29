-- ============================================================
-- Q16 · Revenue Impact of Artworks at Canvas Bucket Boundaries
-- Joins : fct_sales → dim_canvas_size
-- Difficulty : High
-- ============================================================
-- PURPOSE
--   Artworks sitting just inside or outside a size-category boundary
--   may have very different price points despite near-identical
--   physical size.  This query inspects a ±5% band around each
--   boundary (400, 1600, 4000 sq inches) and shows the revenue
--   difference between the two adjacent buckets.
--
-- OUTPUT COLUMNS
--   boundary_label        – e.g. 'Small|Medium boundary @ 400 sq in'
--   category_below        – bucket just below the boundary
--   category_above        – bucket just above the boundary
--   skus_below            – fact rows in the lower bucket in the band
--   skus_above            – fact rows in the upper bucket in the band
--   avg_price_below
--   avg_price_above
--   price_jump_pct        – % jump crossing the boundary
-- ============================================================

WITH boundaries AS (
    SELECT 400  AS boundary_val, 'Small'  AS cat_below, 'Medium'      AS cat_above
    UNION ALL
    SELECT 1600,                  'Medium',               'Large'
    UNION ALL
    SELECT 4000,                  'Large',                'Extra Large'
),
banded AS (
    SELECT
        cs.size_id,
        cs.area_sq_inches,
        cs.size_category,
        fs.sale_price,
        b.boundary_val,
        b.cat_below,
        b.cat_above
    FROM gold.dim_canvas_size  cs
    JOIN gold.fct_sales        fs ON cs.size_id = fs.size_id
    JOIN boundaries        b
         ON cs.area_sq_inches BETWEEN (b.boundary_val * 0.95)
                                   AND (b.boundary_val * 1.05)
    WHERE cs.area_sq_inches IS NOT NULL
)
SELECT
    CONCAT(cat_below, ' | ', cat_above, ' boundary @ ', boundary_val, ' sq in') AS boundary_label,
    cat_below                                                                     AS category_below,
    cat_above                                                                     AS category_above,
    SUM(CASE WHEN size_category = cat_below THEN 1 ELSE 0 END)                   AS skus_below,
    SUM(CASE WHEN size_category = cat_above THEN 1 ELSE 0 END)                   AS skus_above,
    ROUND(AVG(CASE WHEN size_category = cat_below THEN sale_price END)::NUMERIC, 2)  AS avg_price_below,
    ROUND(AVG(CASE WHEN size_category = cat_above THEN sale_price END)::NUMERIC, 2)  AS avg_price_above,
    ROUND(
        100.0 * (
            AVG(CASE WHEN size_category = cat_above THEN sale_price END)
            - AVG(CASE WHEN size_category = cat_below THEN sale_price END)
        ) / NULLIF(AVG(CASE WHEN size_category = cat_below THEN sale_price END), 0),
    2)                                                                             AS price_jump_pct
FROM banded
GROUP BY boundary_label, cat_below, cat_above, boundary_val
ORDER BY boundary_val;