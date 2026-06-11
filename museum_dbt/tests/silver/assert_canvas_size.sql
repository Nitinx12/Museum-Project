-- ============================================================
-- SILVER: canvas_size — 10 assert tests
-- Each SELECT must return 0 rows to pass
-- ============================================================


-- TEST 1: size_id must not be NULL
SELECT
    'TEST 1 – size_id is NULL' AS test_name,
    COUNT(*)                   AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE size_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: size_id must be unique
SELECT
    'TEST 2 – size_id is not unique' AS test_name,
    COUNT(*)                         AS failing_rows
FROM (
    SELECT size_id
    FROM {{ ref('canvas_size') }}
    GROUP BY size_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: label must not be NULL or blank
-- label is the human-readable size name; always expected from source
SELECT
    'TEST 3 – label is NULL or blank' AS test_name,
    COUNT(*)                          AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE NULLIF(TRIM(label), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: width_inches must be positive when present
SELECT
    'TEST 4 – width_inches is zero or negative' AS test_name,
    COUNT(*)                                    AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE width_inches IS NOT NULL
  AND width_inches <= 0
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: height_inches must be positive when present
SELECT
    'TEST 5 – height_inches is zero or negative' AS test_name,
    COUNT(*)                                     AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE height_inches IS NOT NULL
  AND height_inches <= 0
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: width_inches must not exceed a realistic canvas limit (500 inches ≈ 41 ft)
SELECT
    'TEST 6 – width_inches unrealistically large (> 500)' AS test_name,
    COUNT(*)                                              AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE width_inches > 500
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: height_inches must not exceed a realistic canvas limit (500 inches)
SELECT
    'TEST 7 – height_inches unrealistically large (> 500)' AS test_name,
    COUNT(*)                                               AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE height_inches > 500
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: label must not exceed 100 characters (VARCHAR(100) contract)
SELECT
    'TEST 8 – label exceeds 100 chars' AS test_name,
    COUNT(*)                           AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE LENGTH(label) > 100
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: both width_inches and height_inches cannot simultaneously be NULL
-- A size record with no dimensions at all is meaningless
SELECT
    'TEST 9 – both width_inches and height_inches are NULL' AS test_name,
    COUNT(*)                                                AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE width_inches IS NULL
  AND height_inches IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: silver_loaded_at must not be NULL and must not be in the future
SELECT
    'TEST 10 – silver_loaded_at is NULL or in the future' AS test_name,
    COUNT(*)                                              AS failing_rows
FROM {{ ref('canvas_size') }}
WHERE silver_loaded_at IS NULL
   OR silver_loaded_at > CURRENT_TIMESTAMP
HAVING COUNT(*) > 0