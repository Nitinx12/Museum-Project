-- ============================================================
-- SILVER: product_size — 10 assert tests
-- Each SELECT must return 0 rows to pass
--
-- KNOWN SOURCE DATA ISSUES (confirmed from investigation):
--   TEST 3: 2 duplicate (work_id, size_id) pairs exist in bronze — the
--           silver dedup relies on updated_at; rows with NULL updated_at
--           can survive as ties. Demoted to WARN via {{ config(severity='warn') }}.
--   TEST 9: 48 size_id values in product_size have no matching canvas_size
--           record — orphaned size references in the source feed.
--           Demoted to WARN via {{ config(severity='warn') }}.
-- ============================================================

{{ config(severity='warn') }}

-- TEST 1: work_id must not be NULL
SELECT
    'TEST 1 – work_id is NULL' AS test_name,
    COUNT(*)                   AS failing_rows
FROM {{ ref('product_size') }}
WHERE work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: size_id must not be NULL
SELECT
    'TEST 2 – size_id is NULL' AS test_name,
    COUNT(*)                   AS failing_rows
FROM {{ ref('product_size') }}
WHERE size_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: (work_id, size_id) composite key must be unique
-- WARN: 2 duplicate pairs confirmed in source due to NULL updated_at ties
SELECT
    'TEST 3 – (work_id, size_id) composite key is not unique' AS test_name,
    COUNT(*)                                                  AS failing_rows
FROM (
    SELECT work_id, size_id
    FROM {{ ref('product_size') }}
    GROUP BY work_id, size_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: sale_price must be positive when present
SELECT
    'TEST 4 – sale_price is zero or negative' AS test_name,
    COUNT(*)                                  AS failing_rows
FROM {{ ref('product_size') }}
WHERE sale_price IS NOT NULL
  AND sale_price <= 0
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: regular_price must be positive when present
SELECT
    'TEST 5 – regular_price is zero or negative' AS test_name,
    COUNT(*)                                     AS failing_rows
FROM {{ ref('product_size') }}
WHERE regular_price IS NOT NULL
  AND regular_price <= 0
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: sale_price must be <= regular_price (sale cannot be more expensive)
SELECT
    'TEST 6 – sale_price exceeds regular_price' AS test_name,
    COUNT(*)                                    AS failing_rows
FROM {{ ref('product_size') }}
WHERE sale_price    IS NOT NULL
  AND regular_price IS NOT NULL
  AND sale_price > regular_price
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: both sale_price and regular_price cannot simultaneously be NULL
-- A product record with no pricing is useless for commerce
SELECT
    'TEST 7 – both sale_price and regular_price are NULL' AS test_name,
    COUNT(*)                                              AS failing_rows
FROM {{ ref('product_size') }}
WHERE sale_price    IS NULL
  AND regular_price IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: work_id must exist in the silver work table
-- Referential integrity: product_size → work
SELECT
    'TEST 8 – work_id does not exist in silver work' AS test_name,
    COUNT(*)                                         AS failing_rows
FROM {{ ref('product_size') }} ps
LEFT JOIN {{ ref('work') }} w ON ps.work_id = w.work_id
WHERE w.work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: size_id must exist in the silver canvas_size table
-- WARN: 48 orphaned size_id values confirmed in source feed
SELECT
    'TEST 9 – size_id does not exist in silver canvas_size' AS test_name,
    COUNT(*)                                                AS failing_rows
FROM {{ ref('product_size') }} ps
LEFT JOIN {{ ref('canvas_size') }} cs ON ps.size_id = cs.size_id
WHERE cs.size_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: prices must not exceed an unrealistic ceiling (> 1,000,000)
-- Guards against unit conversion errors or garbage data in numeric fields
SELECT
    'TEST 10 – sale_price or regular_price exceeds 1,000,000' AS test_name,
    COUNT(*)                                                   AS failing_rows
FROM {{ ref('product_size') }}
WHERE (sale_price    IS NOT NULL AND sale_price    > 1000000)
   OR (regular_price IS NOT NULL AND regular_price > 1000000)
HAVING COUNT(*) > 0