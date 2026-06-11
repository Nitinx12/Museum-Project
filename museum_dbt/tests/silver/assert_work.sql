-- ============================================================
-- SILVER: work — 10 assert tests
-- Each SELECT must return 0 rows to pass
-- ============================================================


-- TEST 1: work_id must not be NULL
SELECT
    'TEST 1 – work_id is NULL' AS test_name,
    COUNT(*)                   AS failing_rows
FROM {{ ref('work') }}
WHERE work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: work_id must be unique
SELECT
    'TEST 2 – work_id is not unique' AS test_name,
    COUNT(*)                         AS failing_rows
FROM (
    SELECT work_id
    FROM {{ ref('work') }}
    GROUP BY work_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: name (artwork title) must not be NULL or blank
SELECT
    'TEST 3 – work name is NULL or blank' AS test_name,
    COUNT(*)                              AS failing_rows
FROM {{ ref('work') }}
WHERE NULLIF(TRIM(name), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: artist_id must exist in the silver artist table when not NULL
-- Referential integrity: work → artist
SELECT
    'TEST 4 – artist_id does not exist in silver artist' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('work') }} w
LEFT JOIN {{ ref('artist') }} a ON w.artist_id = a.artist_id
WHERE w.artist_id IS NOT NULL
  AND a.artist_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: museum_id must exist in the silver museum table when not NULL
-- Referential integrity: work → museum
SELECT
    'TEST 5 – museum_id does not exist in silver museum' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('work') }} w
LEFT JOIN {{ ref('museum') }} m ON w.museum_id = m.museum_id
WHERE w.museum_id IS NOT NULL
  AND m.museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: name must not exceed 150 characters (VARCHAR(150) contract)
SELECT
    'TEST 6 – work name exceeds 150 chars' AS test_name,
    COUNT(*)                               AS failing_rows
FROM {{ ref('work') }}
WHERE LENGTH(name) > 150
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: style must not exceed 50 characters (VARCHAR(50) contract)
SELECT
    'TEST 7 – style exceeds 50 chars' AS test_name,
    COUNT(*)                          AS failing_rows
FROM {{ ref('work') }}
WHERE LENGTH(style) > 50
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: every work_id in product_size must exist in work
-- Reverse referential integrity: product_size → work
SELECT
    'TEST 8 – product_size has work_id not in silver work' AS test_name,
    COUNT(*)                                              AS failing_rows
FROM {{ ref('product_size') }} ps
LEFT JOIN {{ ref('work') }} w ON ps.work_id = w.work_id
WHERE w.work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: every work_id in subject must exist in work
-- Reverse referential integrity: subject → work
SELECT
    'TEST 9 – subject has work_id not in silver work' AS test_name,
    COUNT(*)                                          AS failing_rows
FROM {{ ref('subject') }} s
LEFT JOIN {{ ref('work') }} w ON s.work_id = w.work_id
WHERE w.work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: updated_at must not be more recent than silver_loaded_at
SELECT
    'TEST 10 – updated_at is after silver_loaded_at' AS test_name,
    COUNT(*)                                         AS failing_rows
FROM {{ ref('work') }}
WHERE updated_at > silver_loaded_at
HAVING COUNT(*) > 0