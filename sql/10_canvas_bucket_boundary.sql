-- ============================================================
-- Q10 · Canvas Size Bucket Boundary & Area Computation Audit
-- Joins : fct_sales → dim_canvas_size
-- Difficulty : High
-- ============================================================
-- PURPOSE
--   Stress-test the CASE bucketing logic in dim_canvas_size.
--   Validates:
--     1. area_sq_inches = ROUND(width_inches * height_inches, 2)
--     2. size_category boundaries are correctly applied
--     3. Artworks near bucket edges are assigned to the right category
--     4. NULL dimension rows correctly land in 'Unknown'
--
-- OUTPUT COLUMNS
--   size_id, label, width_inches, height_inches
--   area_sq_inches       – stored value from model
--   expected_area        – recomputed inline
--   area_mismatch        – 1 if computed ≠ stored (>0.01 tolerance)
--   size_category        – stored category
--   expected_category    – recomputed inline using same CASE logic
--   category_mismatch    – 1 if stored ≠ expected
--   sku_count            – rows in fct_sales with this size_id
-- ============================================================

WITH recomputed AS (
    SELECT
        cs.size_id,
        cs.label,
        cs.width_inches,
        cs.height_inches,
        cs.area_sq_inches,
        cs.size_category,

        -- Recompute area
        CASE
            WHEN cs.width_inches IS NOT NULL AND cs.height_inches IS NOT NULL
                THEN ROUND((cs.width_inches * cs.height_inches)::NUMERIC, 2)
        END                                         AS expected_area,

        -- Recompute category using identical CASE as the model
        CASE
            WHEN cs.width_inches IS NULL OR cs.height_inches IS NULL THEN 'Unknown'
            WHEN (cs.width_inches * cs.height_inches) <=  400        THEN 'Small'
            WHEN (cs.width_inches * cs.height_inches) <= 1600        THEN 'Medium'
            WHEN (cs.width_inches * cs.height_inches) <= 4000        THEN 'Large'
            ELSE                                                          'Extra Large'
        END                                         AS expected_category

    FROM gold.dim_canvas_size cs
),
with_flags AS (
    SELECT
        r.*,
        CASE WHEN ABS(COALESCE(r.area_sq_inches,0) - COALESCE(r.expected_area,0)) > 0.01
             THEN 1 ELSE 0 END                      AS area_mismatch,
        CASE WHEN r.size_category <> r.expected_category
             THEN 1 ELSE 0 END                      AS category_mismatch
    FROM recomputed r
)
SELECT
    f.*,
    COUNT(fs.work_id)                               AS sku_count
FROM with_flags          f
LEFT JOIN gold.fct_sales      fs ON f.size_id = fs.size_id
GROUP BY
    f.size_id, f.label, f.width_inches, f.height_inches,
    f.area_sq_inches, f.size_category, f.expected_area,
    f.expected_category, f.area_mismatch, f.category_mismatch
HAVING f.area_mismatch = 1 OR f.category_mismatch = 1
ORDER BY f.size_id;