-- ============================================================
-- Q15 · COALESCE / NULL-Fallback Coverage Audit (All Dimensions)
-- Joins : dim_artist, dim_artwork, dim_canvas_size, dim_museum  (no fact needed)
-- Difficulty : High
-- ============================================================
-- PURPOSE
--   Every dimension model uses COALESCE or NULLIF to handle missing
--   data.  This query counts how many rows actually triggered each
--   fallback so you can quantify data quality gaps in the source.
--
-- OUTPUT COLUMNS (one row per dimension + column combination)
--   dimension_name         – which model
--   column_name            – which column had the fallback
--   total_rows             – total rows in that dimension
--   fallback_rows          – rows where the default value is showing
--   fallback_pct           – percentage
--   fallback_value         – the default that was applied
-- ============================================================

WITH artist_nulls AS (
    SELECT 'dim_artist'   AS dimension_name,
           'nationality'  AS column_name,
           COUNT(*)       AS total_rows,
           SUM(CASE WHEN nationality = 'Unknown' THEN 1 ELSE 0 END) AS fallback_rows,
           'Unknown'      AS fallback_value
    FROM gold.dim_artist
    UNION ALL
    SELECT 'dim_artist', 'style',
           COUNT(*),
           SUM(CASE WHEN style = 'Unknown' THEN 1 ELSE 0 END),
           'Unknown'
    FROM gold.dim_artist
),
artwork_nulls AS (
    SELECT 'dim_artwork'   AS dimension_name,
           'subject_tags'  AS column_name,
           COUNT(*)        AS total_rows,
           SUM(CASE WHEN subject_tags = 'Unknown' THEN 1 ELSE 0 END) AS fallback_rows,
           'Unknown'       AS fallback_value
    FROM gold.dim_artwork
    UNION ALL
    SELECT 'dim_artwork', 'style (NULLIF blank)',
           COUNT(*),
           SUM(CASE WHEN style IS NULL THEN 1 ELSE 0 END),
           'NULL (blank trimmed)'
    FROM gold.dim_artwork
),
canvas_nulls AS (
    SELECT 'dim_canvas_size' AS dimension_name,
           'label'           AS column_name,
           COUNT(*)          AS total_rows,
           SUM(CASE WHEN label = 'Unknown' THEN 1 ELSE 0 END) AS fallback_rows,
           'Unknown'         AS fallback_value
    FROM gold.dim_canvas_size
    UNION ALL
    SELECT 'dim_canvas_size', 'size_category (Unknown)',
           COUNT(*),
           SUM(CASE WHEN size_category = 'Unknown' THEN 1 ELSE 0 END),
           'Unknown (null dimensions)'
    FROM gold.dim_canvas_size
),
museum_nulls AS (
    SELECT 'dim_museum' AS dimension_name,
           'city'       AS column_name,
           COUNT(*)     AS total_rows,
           SUM(CASE WHEN city = 'Unknown' THEN 1 ELSE 0 END) AS fallback_rows,
           'Unknown'    AS fallback_value
    FROM gold.dim_museum
    UNION ALL
    SELECT 'dim_museum', 'country',
           COUNT(*),
           SUM(CASE WHEN country = 'Unknown' THEN 1 ELSE 0 END),
           'Unknown'
    FROM gold.dim_museum
)
SELECT
    dimension_name,
    column_name,
    total_rows,
    fallback_rows,
    ROUND(100.0 * fallback_rows / NULLIF(total_rows, 0), 2) AS fallback_pct,
    fallback_value
FROM (
    SELECT * FROM artist_nulls
    UNION ALL SELECT * FROM artwork_nulls
    UNION ALL SELECT * FROM canvas_nulls
    UNION ALL SELECT * FROM museum_nulls
) all_nulls
ORDER BY dimension_name, fallback_pct DESC;