-- ============================================================
-- GOLD: dim_artwork — 10 assert tests
-- Each query must return 0 rows to pass
-- ============================================================


-- TEST 1: work_id (PK) must not be NULL
SELECT
    'TEST 1 – work_id is NULL' AS test_name,
    COUNT(*)                   AS failing_rows
FROM {{ ref('dim_artwork') }}
WHERE work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: work_id must be unique
SELECT
    'TEST 2 – work_id is not unique' AS test_name,
    COUNT(*)                         AS failing_rows
FROM (
    SELECT work_id
    FROM {{ ref('dim_artwork') }}
    GROUP BY work_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: artwork_name must not be NULL or blank
SELECT
    'TEST 3 – artwork_name is NULL or blank' AS test_name,
    COUNT(*)                                 AS failing_rows
FROM {{ ref('dim_artwork') }}
WHERE NULLIF(TRIM(artwork_name), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: subject_tags must not be NULL (model defaults to 'Unknown')
SELECT
    'TEST 4 – subject_tags is NULL' AS test_name,
    COUNT(*)                        AS failing_rows
FROM {{ ref('dim_artwork') }}
WHERE subject_tags IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: artist_id must resolve to dim_artist when not NULL (no orphan artworks)
SELECT
    'TEST 5 – artist_id is orphaned (not in dim_artist)' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('dim_artwork') }} da
LEFT JOIN {{ ref('dim_artist') }} ar ON da.artist_id = ar.artist_id
WHERE da.artist_id IS NOT NULL
  AND ar.artist_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: museum_id must resolve to dim_museum when not NULL (no orphan artworks)
SELECT
    'TEST 6 – museum_id is orphaned (not in dim_museum)' AS test_name,
    COUNT(*)                                             AS failing_rows
FROM {{ ref('dim_artwork') }} da
LEFT JOIN {{ ref('dim_museum') }} m ON da.museum_id = m.museum_id
WHERE da.museum_id IS NOT NULL
  AND m.museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: every work_id in fct_sales must exist in dim_artwork
-- Reverse check: fact rows must never reference a work that was dropped from the dim
SELECT
    'TEST 7 – fct_sales has work_id not in dim_artwork' AS test_name,
    COUNT(*)                                            AS failing_rows
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ ref('dim_artwork') }} da ON f.work_id = da.work_id
WHERE da.work_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: subject_tags must not be an empty string (COALESCE should prevent this)
SELECT
    'TEST 8 – subject_tags is an empty string' AS test_name,
    COUNT(*)                                   AS failing_rows
FROM {{ ref('dim_artwork') }}
WHERE TRIM(subject_tags) = ''
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: style must not exceed 50 characters (inherited from silver VARCHAR(50))
SELECT
    'TEST 9 – style exceeds 50 chars' AS test_name,
    COUNT(*)                          AS failing_rows
FROM {{ ref('dim_artwork') }}
WHERE LENGTH(style) > 50
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: artworks with a museum_id must have that museum also present in fct_sales
-- Ensures museum assignments flow correctly end-to-end to the fact table
SELECT
    'TEST 10 – artwork museum_id not reflected in fct_sales' AS test_name,
    COUNT(*)                                                 AS failing_rows
FROM {{ ref('dim_artwork') }} da
WHERE da.museum_id IS NOT NULL
  AND EXISTS (
      -- Only check artworks that actually have sales records
      SELECT 1 FROM {{ ref('fct_sales') }} f WHERE f.work_id = da.work_id
  )
  AND NOT EXISTS (
      SELECT 1
      FROM {{ ref('fct_sales') }} f
      WHERE f.work_id   = da.work_id
        AND f.museum_id = da.museum_id
  )
HAVING COUNT(*) > 0