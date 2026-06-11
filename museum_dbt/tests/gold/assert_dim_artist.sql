-- ============================================================
-- GOLD: dim_artist — 10 assert tests
-- Each query must return 0 rows to pass
-- ============================================================


-- TEST 1: artist_id (PK) must not be NULL
SELECT
    'TEST 1 – artist_id is NULL' AS test_name,
    COUNT(*)                     AS failing_rows
FROM {{ ref('dim_artist') }}
WHERE artist_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: artist_id must be unique
SELECT
    'TEST 2 – artist_id is not unique' AS test_name,
    COUNT(*)                           AS failing_rows
FROM (
    SELECT artist_id
    FROM {{ ref('dim_artist') }}
    GROUP BY artist_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: artist_name must not be NULL or blank
SELECT
    'TEST 3 – artist_name is NULL or blank' AS test_name,
    COUNT(*)                                AS failing_rows
FROM {{ ref('dim_artist') }}
WHERE NULLIF(TRIM(artist_name), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: nationality must not be NULL (model defaults to 'Unknown')
SELECT
    'TEST 4 – nationality is NULL' AS test_name,
    COUNT(*)                       AS failing_rows
FROM {{ ref('dim_artist') }}
WHERE nationality IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: era must be one of the 8 valid buckets (CASE logic completeness check)
SELECT
    'TEST 5 – era contains an unexpected value' AS test_name,
    COUNT(*)                                    AS failing_rows
FROM {{ ref('dim_artist') }}
WHERE era NOT IN (
    'Medieval & Earlier',
    'Renaissance',
    'Baroque & Rococo',
    'Neoclassical & Romantic',
    'Impressionist Era',
    'Modern',
    'Contemporary',
    'Unknown'
)
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: artist_status must only be 'Historical' or 'Living / Unknown'
SELECT
    'TEST 6 – artist_status has unexpected value' AS test_name,
    COUNT(*)                                      AS failing_rows
FROM {{ ref('dim_artist') }}
WHERE artist_status NOT IN ('Historical', 'Living / Unknown')
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: artist_status = 'Historical' must always have a death_year
-- If death_year is NULL the CASE logic is broken
SELECT
    'TEST 7 – Historical artist has NULL death_year' AS test_name,
    COUNT(*)                                         AS failing_rows
FROM {{ ref('dim_artist') }}
WHERE artist_status = 'Historical'
  AND death_year IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: death_year must be >= birth_year when both are present
SELECT
    'TEST 8 – death_year is before birth_year' AS test_name,
    COUNT(*)                                   AS failing_rows
FROM {{ ref('dim_artist') }}
WHERE birth_year IS NOT NULL
  AND death_year IS NOT NULL
  AND death_year < birth_year
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: era = 'Unknown' must only occur when birth_year IS NULL
-- If birth_year is populated, the CASE should assign a real era bucket
SELECT
    'TEST 9 – era is Unknown but birth_year is populated' AS test_name,
    COUNT(*)                                              AS failing_rows
FROM {{ ref('dim_artist') }}
WHERE era = 'Unknown'
  AND birth_year IS NOT NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: every artist_id referenced in dim_artwork must exist in dim_artist
-- Referential integrity: artwork → artist across the gold layer
SELECT
    'TEST 10 – dim_artwork references artist_id not in dim_artist' AS test_name,
    COUNT(*)                                                       AS failing_rows
FROM {{ ref('dim_artwork') }} da
LEFT JOIN {{ ref('dim_artist') }} ar ON da.artist_id = ar.artist_id
WHERE da.artist_id IS NOT NULL
  AND ar.artist_id IS NULL
HAVING COUNT(*) > 0