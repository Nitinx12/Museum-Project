-- ============================================================
-- Q17 · Missing Metadata Orphan Analysis Across All Dimensions
-- Joins : fct_sales → dim_artwork → dim_artist → dim_canvas_size → dim_museum
-- Difficulty : High
-- ============================================================
-- PURPOSE
--   Find fact rows that have degraded joins — i.e., they map to
--   dimension rows that fell into fallback/unknown values.  These
--   rows can skew aggregate reports.  The query scores each fact
--   row by how many dimensions have unknown/null metadata and
--   summarises the revenue at risk from poor metadata.
--
-- OUTPUT COLUMNS
--   metadata_quality_score   – 0 (all clean) to 4 (all dims unknown)
--   sku_count                – fact rows with that score
--   distinct_artworks
--   total_sale_revenue
--   pct_of_total_revenue
--   flags_breakdown          – pipe-separated list of which dims failed
-- ============================================================

WITH flagged AS (
    SELECT
        fs.sales_key,
        fs.work_id,
        fs.sale_price,

        -- Flag each unknown dimension (1 = unknown/null)
        CASE WHEN da.nationality   = 'Unknown' THEN 1 ELSE 0 END  AS flag_artist_nationality,
        CASE WHEN da.style         = 'Unknown' THEN 1 ELSE 0 END  AS flag_artist_style,
        CASE WHEN aw.subject_tags  = 'Unknown' THEN 1 ELSE 0 END  AS flag_artwork_subject,
        CASE WHEN cs.size_category = 'Unknown' THEN 1 ELSE 0 END  AS flag_canvas_unknown,
        CASE WHEN dm.city          = 'Unknown' OR dm.museum_id IS NULL
             THEN 1 ELSE 0 END                                     AS flag_museum_unknown

    FROM gold.fct_sales       fs
    JOIN gold.dim_artwork     aw ON fs.work_id   = aw.work_id
    JOIN gold.dim_artist      da ON fs.artist_id = da.artist_id
    JOIN gold.dim_canvas_size cs ON fs.size_id   = cs.size_id
    LEFT JOIN gold.dim_museum dm ON fs.museum_id = dm.museum_id
),
scored AS (
    SELECT
        *,
        (flag_artist_nationality + flag_artist_style
         + flag_artwork_subject  + flag_canvas_unknown
         + flag_museum_unknown)                            AS metadata_quality_score,
        TRIM(
            CONCAT_WS(' | ',
                CASE WHEN flag_artist_nationality=1 THEN 'Nationality' END,
                CASE WHEN flag_artist_style      =1 THEN 'Artist Style' END,
                CASE WHEN flag_artwork_subject   =1 THEN 'Subject Tags' END,
                CASE WHEN flag_canvas_unknown    =1 THEN 'Canvas Size' END,
                CASE WHEN flag_museum_unknown    =1 THEN 'Museum' END
            )
        )                                                 AS flags_breakdown
    FROM flagged
),
totals AS (SELECT SUM(sale_price) AS grand_total FROM gold.fct_sales)
SELECT
    metadata_quality_score,
    COUNT(*)                                                        AS sku_count,
    COUNT(DISTINCT work_id)                                         AS distinct_artworks,
    ROUND(SUM(sale_price)::NUMERIC,  2)                             AS total_sale_revenue,
    ROUND(
        100.0 * SUM(sale_price) / NULLIF((SELECT grand_total FROM totals), 0),
    2)                                                              AS pct_of_total_revenue,
    MODE() WITHIN GROUP (ORDER BY flags_breakdown)                  AS most_common_flag_combo
FROM scored
GROUP BY metadata_quality_score
ORDER BY metadata_quality_score;