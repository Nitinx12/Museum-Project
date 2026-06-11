-- ============================================================
-- SILVER: museum — 10 assert tests
-- Each SELECT must return 0 rows to pass
-- ============================================================


-- TEST 1: museum_id must not be NULL
SELECT
    'TEST 1 – museum_id is NULL' AS test_name,
    COUNT(*)                     AS failing_rows
FROM {{ ref('museum') }}
WHERE museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: museum_id must be unique
SELECT
    'TEST 2 – museum_id is not unique' AS test_name,
    COUNT(*)                           AS failing_rows
FROM (
    SELECT museum_id
    FROM {{ ref('museum') }}
    GROUP BY museum_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: museum_name must not be NULL or blank
SELECT
    'TEST 3 – museum_name is NULL or blank' AS test_name,
    COUNT(*)                                AS failing_rows
FROM {{ ref('museum') }}
WHERE NULLIF(TRIM(museum_name), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: country must not be NULL or blank
-- Every museum must belong to a country for geo reporting
SELECT
    'TEST 4 – country is NULL or blank' AS test_name,
    COUNT(*)                            AS failing_rows
FROM {{ ref('museum') }}
WHERE NULLIF(TRIM(country), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: city must not be purely numeric after cleaning
-- The model fixes swapped city/postal; this catches any that slipped through
SELECT
    'TEST 5 – city is still purely numeric after cleaning' AS test_name,
    COUNT(*)                                               AS failing_rows
FROM {{ ref('museum') }}
WHERE city ~ '^[0-9]+$'
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: url must start with http:// or https:// when present
SELECT
    'TEST 6 – url has invalid format (not http/https)' AS test_name,
    COUNT(*)                                           AS failing_rows
FROM {{ ref('museum') }}
WHERE url IS NOT NULL
  AND url NOT ILIKE 'http://%'
  AND url NOT ILIKE 'https://%'
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: phone must not exceed 30 characters (VARCHAR(30) contract)
SELECT
    'TEST 7 – phone exceeds 30 chars' AS test_name,
    COUNT(*)                          AS failing_rows
FROM {{ ref('museum') }}
WHERE LENGTH(phone) > 30
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: museum_name must not exceed 100 characters (VARCHAR(100) contract)
SELECT
    'TEST 8 – museum_name exceeds 100 chars' AS test_name,
    COUNT(*)                                 AS failing_rows
FROM {{ ref('museum') }}
WHERE LENGTH(museum_name) > 100
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: every museum_id in museum_hours must exist in museum
-- Referential integrity: child → parent
SELECT
    'TEST 9 – museum_hours has museum_id not in museum' AS test_name,
    COUNT(*)                                            AS failing_rows
FROM {{ ref('museum_hours') }} mh
LEFT JOIN {{ ref('museum') }} m ON mh.museum_id = m.museum_id
WHERE m.museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: every museum_id in work must exist in museum
-- Referential integrity: artwork → museum
SELECT
    'TEST 10 – work has museum_id not in museum' AS test_name,
    COUNT(*)                                     AS failing_rows
FROM {{ ref('work') }} w
LEFT JOIN {{ ref('museum') }} m ON w.museum_id = m.museum_id
WHERE w.museum_id IS NOT NULL
  AND m.museum_id IS NULL
HAVING COUNT(*) > 0