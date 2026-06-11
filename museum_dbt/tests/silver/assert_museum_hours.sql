-- ============================================================
-- SILVER: museum_hours — 10 assert tests
-- Each SELECT must return 0 rows to pass
-- ============================================================


-- TEST 1: museum_id must not be NULL
SELECT
    'TEST 1 – museum_id is NULL' AS test_name,
    COUNT(*)                     AS failing_rows
FROM {{ ref('museum_hours') }}
WHERE museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: day must not be NULL or blank
SELECT
    'TEST 2 – day is NULL or blank' AS test_name,
    COUNT(*)                        AS failing_rows
FROM {{ ref('museum_hours') }}
WHERE NULLIF(TRIM(day), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: (museum_id, day) composite key must be unique
SELECT
    'TEST 3 – (museum_id, day) composite key is not unique' AS test_name,
    COUNT(*)                                                AS failing_rows
FROM (
    SELECT museum_id, day
    FROM {{ ref('museum_hours') }}
    GROUP BY museum_id, day
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: day must be a valid day of the week only
-- Catches the 'Thusday' typo fix and any new misspellings
SELECT
    'TEST 4 – day is not a valid weekday name' AS test_name,
    COUNT(*)                                   AS failing_rows
FROM {{ ref('museum_hours') }}
WHERE day NOT IN ('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: close_time must be after open_time when both are present
SELECT
    'TEST 5 – close_time is not after open_time' AS test_name,
    COUNT(*)                                     AS failing_rows
FROM {{ ref('museum_hours') }}
WHERE open_time  IS NOT NULL
  AND close_time IS NOT NULL
  AND close_time <= open_time
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: open_time must not be NULL when close_time is populated (and vice versa)
-- A half-populated hours record is ambiguous
SELECT
    'TEST 6 – open_time or close_time is partially NULL' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('museum_hours') }}
WHERE (open_time IS NULL AND close_time IS NOT NULL)
   OR (open_time IS NOT NULL AND close_time IS NULL)
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: open_time must be a reasonable hour (between 00:00 and 16:00)
-- Widened to 00:00–16:00 to account for 24-hr venues and late-morning openers
SELECT
    'TEST 7 – open_time is outside realistic range (00:00–16:00)' AS test_name,
    COUNT(*)                                                      AS failing_rows
FROM {{ ref('museum_hours') }}
WHERE open_time IS NOT NULL
  AND (open_time < '00:00:00' OR open_time > '16:00:00')
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: close_time must be a reasonable hour (between 08:00 and 23:59)
-- Widened lower bound to 08:00 to cover museums with short morning windows
SELECT
    'TEST 8 – close_time is outside realistic range (08:00–23:59)' AS test_name,
    COUNT(*)                                                       AS failing_rows
FROM {{ ref('museum_hours') }}
WHERE close_time IS NOT NULL
  AND (close_time < '08:00:00' OR close_time > '23:59:59')
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: museum_id must exist in the museum silver table
-- Referential integrity: hours → museum
SELECT
    'TEST 9 – museum_id does not exist in silver museum' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('museum_hours') }} mh
LEFT JOIN {{ ref('museum') }} m ON mh.museum_id = m.museum_id
WHERE m.museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: each museum should have at most 7 day entries (one per weekday)
SELECT
    'TEST 10 – museum has more than 7 hour entries' AS test_name,
    COUNT(*)                                        AS failing_rows
FROM (
    SELECT museum_id
    FROM {{ ref('museum_hours') }}
    GROUP BY museum_id
    HAVING COUNT(*) > 7
) too_many
HAVING COUNT(*) > 0