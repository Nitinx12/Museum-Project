-- ============================================================
-- GOLD: fct_sales — 10 assert tests
-- Each query must return 0 rows to pass
-- ============================================================


-- TEST 1: sales_key (surrogate PK) must not be NULL
SELECT
    'TEST 1 – sales_key is NULL' AS test_name,
    COUNT(*)                     AS failing_rows
FROM {{ ref('fct_sales') }}
WHERE sales_key IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: sales_key must be unique (no duplicate surrogate keys)
SELECT
    'TEST 2 – sales_key is not unique' AS test_name,
    COUNT(*)                           AS failing_rows
FROM (
    SELECT sales_key
    FROM {{ ref('fct_sales') }}
    GROUP BY sales_key
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: work_id must resolve to a row in dim_artwork (no orphan fact rows)
SELECT
    'TEST 3 – work_id is orphaned (not in dim_artwork)' AS test_name,
    COUNT(*)                                            AS failing_rows
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ ref('dim_artwork') }} d ON f.work_id = d.work_id
WHERE d.work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: size_id must resolve to a row in dim_canvas_size (no orphan fact rows)
SELECT
    'TEST 4 – size_id is orphaned (not in dim_canvas_size)' AS test_name,
    COUNT(*)                                                AS failing_rows
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ ref('dim_canvas_size') }} d ON f.size_id = d.size_id
WHERE d.size_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: artist_id must resolve to dim_artist when not NULL
SELECT
    'TEST 5 – artist_id is orphaned (not in dim_artist)' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ ref('dim_artist') }} d ON f.artist_id = d.artist_id
WHERE f.artist_id IS NOT NULL
  AND d.artist_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: museum_id must resolve to dim_museum when not NULL
SELECT
    'TEST 6 – museum_id is orphaned (not in dim_museum)' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ ref('dim_museum') }} d ON f.museum_id = d.museum_id
WHERE f.museum_id IS NOT NULL
  AND d.museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: sale_price and regular_price must not both be NULL
SELECT
    'TEST 7 – both sale_price and regular_price are NULL' AS test_name,
    COUNT(*)                                              AS failing_rows
FROM {{ ref('fct_sales') }}
WHERE sale_price    IS NULL
  AND regular_price IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: discount_amount must equal (regular_price - sale_price) when both are present
-- Catches any rounding or computation drift in the derived column
SELECT
    'TEST 8 – discount_amount does not match (regular_price - sale_price)' AS test_name,
    COUNT(*)                                                                AS failing_rows
FROM {{ ref('fct_sales') }}
WHERE sale_price      IS NOT NULL
  AND regular_price   IS NOT NULL
  AND ABS(discount_amount - ROUND((regular_price - sale_price)::NUMERIC, 2)) > 0.01
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: discount_pct must be between 0 and 100 when present
SELECT
    'TEST 9 – discount_pct is outside 0–100 range' AS test_name,
    COUNT(*)                                        AS failing_rows
FROM {{ ref('fct_sales') }}
WHERE discount_pct IS NOT NULL
  AND (discount_pct < 0 OR discount_pct > 100)
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: is_in_museum must be TRUE only when museum_id is actually populated
-- Consistency check between the flag and the FK
SELECT
    'TEST 10 – is_in_museum flag contradicts museum_id' AS test_name,
    COUNT(*)                                            AS failing_rows
FROM {{ ref('fct_sales') }}
WHERE (is_in_museum = TRUE  AND museum_id IS NULL)
   OR (is_in_museum = FALSE AND museum_id IS NOT NULL)
HAVING COUNT(*) > 0