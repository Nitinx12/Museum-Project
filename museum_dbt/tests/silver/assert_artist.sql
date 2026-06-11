-- ============================================================
-- SILVER: artist — 10 assert tests
-- Each SELECT must return 0 rows to pass
-- ============================================================


-- TEST 1: artist_id must not be NULL
-- Catches rows that slipped past the bronze filter
SELECT
    'TEST 1 – artist_id is NULL' AS test_name,
    COUNT(*)                     AS failing_rows
FROM {{ ref('artist') }}
WHERE artist_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: artist_id must be unique
-- Duplicate IDs break every downstream JOIN
SELECT
    'TEST 2 – artist_id is not unique' AS test_name,
    COUNT(*)                           AS failing_rows
FROM (
    SELECT artist_id
    FROM {{ ref('artist') }}
    GROUP BY artist_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: artist_name must not be NULL or blank
-- silver model concatenates name parts; empty result means all parts were NULL
SELECT
    'TEST 3 – artist_name is NULL or blank' AS test_name,
    COUNT(*)                                AS failing_rows
FROM {{ ref('artist') }}
WHERE NULLIF(TRIM(artist_name), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: birth_year must be positive and realistic (> 0 and <= current year)
SELECT
    'TEST 4 – birth_year out of realistic range' AS test_name,
    COUNT(*)                                     AS failing_rows
FROM {{ ref('artist') }}
WHERE birth_year IS NOT NULL
  AND (birth_year <= 0 OR birth_year > EXTRACT(YEAR FROM CURRENT_DATE))
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: death_year must be positive and realistic (> 0 and <= current year)
SELECT
    'TEST 5 – death_year out of realistic range' AS test_name,
    COUNT(*)                                     AS failing_rows
FROM {{ ref('artist') }}
WHERE death_year IS NOT NULL
  AND (death_year <= 0 OR death_year > EXTRACT(YEAR FROM CURRENT_DATE))
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: death_year must be >= birth_year (cannot die before being born)
SELECT
    'TEST 6 – death_year < birth_year' AS test_name,
    COUNT(*)                           AS failing_rows
FROM {{ ref('artist') }}
WHERE death_year IS NOT NULL
  AND birth_year IS NOT NULL
  AND death_year < birth_year
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: nationality must not exceed 50 characters (VARCHAR(50) contract)
SELECT
    'TEST 7 – nationality exceeds 50 chars' AS test_name,
    COUNT(*)                                AS failing_rows
FROM {{ ref('artist') }}
WHERE LENGTH(nationality) > 50
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: style must not exceed 50 characters (VARCHAR(50) contract)
SELECT
    'TEST 8 – style exceeds 50 chars' AS test_name,
    COUNT(*)                          AS failing_rows
FROM {{ ref('artist') }}
WHERE LENGTH(style) > 50
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: silver_loaded_at must not be NULL and must not be in the future
SELECT
    'TEST 9 – silver_loaded_at is NULL or in the future' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('artist') }}
WHERE silver_loaded_at IS NULL
   OR silver_loaded_at > CURRENT_TIMESTAMP
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: updated_at must not be more recent than silver_loaded_at
-- (source timestamp cannot be ahead of the pipeline run time)
SELECT
    'TEST 10 – updated_at is after silver_loaded_at' AS test_name,
    COUNT(*)                                         AS failing_rows
FROM {{ ref('artist') }}
WHERE updated_at > silver_loaded_at
HAVING COUNT(*) > 0