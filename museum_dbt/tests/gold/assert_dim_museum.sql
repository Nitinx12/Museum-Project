-- ============================================================
-- GOLD: dim_museum — 10 assert tests
-- Each query must return 0 rows to pass
-- ============================================================


-- TEST 1: museum_id (PK) must not be NULL
SELECT
    'TEST 1 – museum_id is NULL' AS test_name,
    COUNT(*)                     AS failing_rows
FROM {{ ref('dim_museum') }}
WHERE museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 2: museum_id must be unique
SELECT
    'TEST 2 – museum_id is not unique' AS test_name,
    COUNT(*)                           AS failing_rows
FROM (
    SELECT museum_id
    FROM {{ ref('dim_museum') }}
    GROUP BY museum_id
    HAVING COUNT(*) > 1
) dupes
HAVING COUNT(*) > 0

UNION ALL

-- TEST 3: museum_name must not be NULL or blank
SELECT
    'TEST 3 – museum_name is NULL or blank' AS test_name,
    COUNT(*)                                AS failing_rows
FROM {{ ref('dim_museum') }}
WHERE NULLIF(TRIM(museum_name), '') IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 4: country must not be NULL (model defaults to 'Unknown')
SELECT
    'TEST 4 – country is NULL' AS test_name,
    COUNT(*)                   AS failing_rows
FROM {{ ref('dim_museum') }}
WHERE country IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 5: opening_days_per_week must be between 0 and 7
SELECT
    'TEST 5 – opening_days_per_week is outside 0–7' AS test_name,
    COUNT(*)                                        AS failing_rows
FROM {{ ref('dim_museum') }}
WHERE opening_days_per_week < 0
   OR opening_days_per_week > 7
HAVING COUNT(*) > 0

UNION ALL

-- TEST 6: avg_daily_open_hours must be positive and at most 24 when present
SELECT
    'TEST 6 – avg_daily_open_hours is outside 0–24' AS test_name,
    COUNT(*)                                        AS failing_rows
FROM {{ ref('dim_museum') }}
WHERE avg_daily_open_hours IS NOT NULL
  AND (avg_daily_open_hours <= 0 OR avg_daily_open_hours > 24)
HAVING COUNT(*) > 0

UNION ALL

-- TEST 7: latest_close_time must be after earliest_open_time when both are present
SELECT
    'TEST 7 – latest_close_time is not after earliest_open_time' AS test_name,
    COUNT(*)                                                     AS failing_rows
FROM {{ ref('dim_museum') }}
WHERE earliest_open_time IS NOT NULL
  AND latest_close_time  IS NOT NULL
  AND latest_close_time <= earliest_open_time
HAVING COUNT(*) > 0

UNION ALL

-- TEST 8: museums with opening_days_per_week = 0 must have NULL avg_daily_open_hours
-- A museum with no operating days cannot have an average open duration
SELECT
    'TEST 8 – museum has 0 opening days but non-NULL avg_daily_open_hours' AS test_name,
    COUNT(*)                                                               AS failing_rows
FROM {{ ref('dim_museum') }}
WHERE opening_days_per_week = 0
  AND avg_daily_open_hours IS NOT NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 9: every museum_id in fct_sales must exist in dim_museum (no orphan fact rows)
SELECT
    'TEST 9 – fct_sales references museum_id not in dim_museum' AS test_name,
    COUNT(*)                                                    AS failing_rows
FROM {{ ref('fct_sales') }} f
LEFT JOIN {{ ref('dim_museum') }} m ON f.museum_id = m.museum_id
WHERE f.museum_id IS NOT NULL
  AND m.museum_id IS NULL
HAVING COUNT(*) > 0

UNION ALL

-- TEST 10: url must start with http:// or https:// when present
-- Inherited from silver but re-checked to catch any new data entering gold
SELECT
    'TEST 10 – url has invalid format' AS test_name,
    COUNT(*)                           AS failing_rows
FROM {{ ref('dim_museum') }}
WHERE url IS NOT NULL
  AND url NOT ILIKE 'http://%'
  AND url NOT ILIKE 'https://%'
HAVING COUNT(*) > 0