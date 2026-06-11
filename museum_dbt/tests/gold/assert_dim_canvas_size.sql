-- ============================================================
-- GOLD: dim_canvas_size — 10 assert tests
-- Each query must return 0 rows to pass
-- ============================================================


-- TEST 1: size_id (PK) must not be NULL
SELECT
    'TEST 1 – size_id is NULL' AS test_name,
    COUNT(*)                   AS failing_rows
FROM {{ ref('dim_canvas_size') }}
WHERE size_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: size_id must be unique
SELECT
    'TEST 2 – size_id is not unique' AS test_name,
    COUNT(*)                         AS failing_rows
FROM (
    SELECT size_id
    FROM {{ ref('dim_canvas_size') }}
    GROUP BY size_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: label must not be NULL (model defaults to 'Unknown')
SELECT
    'TEST 3 – label is NULL' AS test_name,
    COUNT(*)                 AS failing_rows
FROM {{ ref('dim_canvas_size') }}
WHERE label IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: size_category must be one of the 5 valid buckets
SELECT
    'TEST 4 – size_category contains unexpected value' AS test_name,
    COUNT(*)                                           AS failing_rows
FROM {{ ref('dim_canvas_size') }}
WHERE size_category NOT IN ('Small', 'Medium', 'Large', 'Extra Large', 'Unknown')
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: size_category = 'Unknown' must only occur when width or height is NULL
-- If both dimensions are present, CASE logic must assign a real bucket
SELECT
    'TEST 5 – size_category is Unknown but both dimensions are populated' AS test_name,
    COUNT(*)                                                              AS failing_rows
FROM {{ ref('dim_canvas_size') }}
WHERE size_category  = 'Unknown'
  AND width_inches  IS NOT NULL
  AND height_inches IS NOT NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: area_sq_inches must equal width_inches * height_inches when both are present
-- Catches any computation drift in the derived column
SELECT
    'TEST 6 – area_sq_inches does not match width × height' AS test_name,
    COUNT(*)                                                AS failing_rows
FROM {{ ref('dim_canvas_size') }}
WHERE width_inches   IS NOT NULL
  AND height_inches  IS NOT NULL
  AND ABS(area_sq_inches - ROUND((width_inches * height_inches)::NUMERIC, 2)) > 0.01
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: area_sq_inches must be NULL when either dimension is missing
SELECT
    'TEST 7 – area_sq_inches is populated but a dimension is NULL' AS test_name,
    COUNT(*)                                                       AS failing_rows
FROM {{ ref('dim_canvas_size') }}
WHERE area_sq_inches IS NOT NULL
  AND (width_inches IS NULL OR height_inches IS NULL)
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: width_inches and height_inches must be positive when present
SELECT
    'TEST 8 – width_inches or height_inches is zero or negative' AS test_name,
    COUNT(*)                                                     AS failing_rows
FROM {{ ref('dim_canvas_size') }}
WHERE (width_inches  IS NOT NULL AND width_inches  <= 0)
   OR (height_inches IS NOT NULL AND height_inches <= 0)
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: every size_id in fct_sales must exist in dim_canvas_size (no orphan fact rows)
SELECT
    'TEST 9 – fct_sales references size_id not in dim_canvas_size' AS test_name,
    COUNT(*)                                                       AS failing_rows
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ ref('dim_canvas_size') }} cs ON f.size_id = cs.size_id
WHERE cs.size_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: label must not exceed 100 characters (inherited from silver VARCHAR(100))
SELECT
    'TEST 10 – label exceeds 100 chars' AS test_name,
    COUNT(*)                            AS failing_rows
FROM {{ ref('dim_canvas_size') }}
WHERE LENGTH(label) > 100
HAVING COUNT(*) > 0