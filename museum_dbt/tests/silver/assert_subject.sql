-- ============================================================
-- SILVER: subject — 10 assert tests
-- Each SELECT must return 0 rows to pass
-- ============================================================


-- TEST 1: work_id must not be NULL
SELECT
    'TEST 1 – work_id is NULL' AS test_name,
    COUNT(*)                   AS failing_rows
FROM {{ ref('subject') }}
WHERE work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: subject must not be NULL or blank
SELECT
    'TEST 2 – subject is NULL or blank' AS test_name,
    COUNT(*)                            AS failing_rows
FROM {{ ref('subject') }}
WHERE NULLIF(TRIM(subject), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: (work_id, subject) composite key must be unique
SELECT
    'TEST 3 – (work_id, subject) composite key is not unique' AS test_name,
    COUNT(*)                                                  AS failing_rows
FROM (
    SELECT work_id, subject
    FROM {{ ref('subject') }}
    GROUP BY work_id, subject
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: work_id must exist in the silver work table
-- Referential integrity: subject tag → work
SELECT
    'TEST 4 – work_id does not exist in silver work' AS test_name,
    COUNT(*)                                         AS failing_rows
FROM {{ ref('subject') }} s
LEFT JOIN {{ ref('work') }} w ON s.work_id = w.work_id
WHERE w.work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: subject must not exceed 100 characters (VARCHAR(100) contract)
SELECT
    'TEST 5 – subject exceeds 100 chars' AS test_name,
    COUNT(*)                             AS failing_rows
FROM {{ ref('subject') }}
WHERE LENGTH(subject) > 100
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: subject must not contain leading or trailing whitespace after TRIM
-- Detects cases where TRIM was not applied correctly during transformation
SELECT
    'TEST 6 – subject has leading or trailing whitespace' AS test_name,
    COUNT(*)                                              AS failing_rows
FROM {{ ref('subject') }}
WHERE subject != TRIM(subject)
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: subject must not be a pure number
-- Numeric-only subjects are likely a misloaded key or data corruption
SELECT
    'TEST 7 – subject is purely numeric' AS test_name,
    COUNT(*)                             AS failing_rows
FROM {{ ref('subject') }}
WHERE subject ~ '^[0-9]+$'
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: a single work_id must not have an excessive number of subjects (> 30)
-- More than 30 subject tags on one work suggests runaway or duplicated tagging
SELECT
    'TEST 8 – work_id has more than 30 subject tags' AS test_name,
    COUNT(*)                                         AS failing_rows
FROM (
    SELECT work_id
    FROM {{ ref('subject') }}
    GROUP BY work_id
    HAVING COUNT(*) > 30
) too_many
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: loaded_at must not be in the future
SELECT
    'TEST 9 – loaded_at is in the future' AS test_name,
    COUNT(*)                              AS failing_rows
FROM {{ ref('subject') }}
WHERE loaded_at IS NOT NULL
  AND loaded_at > CURRENT_TIMESTAMP
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: silver_loaded_at must not be NULL and must not be in the future
SELECT
    'TEST 10 – silver_loaded_at is NULL or in the future' AS test_name,
    COUNT(*)                                              AS failing_rows
FROM {{ ref('subject') }}
WHERE silver_loaded_at IS NULL
   OR silver_loaded_at > CURRENT_TIMESTAMP
HAVING COUNT(*) > 0