-- ============================================================
-- Q19 · is_in_museum Flag Integrity Audit  ← SINGLE TABLE + dim_artwork
-- Joins : fct_sales only for the main audit; dim_artwork for cross-check
-- Difficulty : High
-- ============================================================
-- PURPOSE
--   The is_in_museum flag in fct_sales is derived as:
--     CASE WHEN a.museum_id IS NOT NULL THEN TRUE ELSE FALSE END
--   where `a` is dim_artwork joined on work_id.
--
--   This audit verifies:
--     1. All rows with is_in_museum = TRUE have a non-NULL museum_id in fct_sales
--     2. All rows with is_in_museum = FALSE have museum_id IS NULL in fct_sales
--     3. The fct_sales.museum_id aligns with dim_artwork.museum_id for every work
--     4. There are no rows where museum_id is populated but flag is FALSE (and vice versa)
--
-- OUTPUT COLUMNS (summary counts — all should be 0 for a clean model)
--   flag_true_but_null_museum    – is_in_museum=TRUE yet museum_id IS NULL
--   flag_false_but_has_museum    – is_in_museum=FALSE yet museum_id IS NOT NULL
--   fact_museum_vs_artwork_mismatch – fct_sales.museum_id ≠ dim_artwork.museum_id
--   total_in_museum              – total rows flagged TRUE
--   total_not_in_museum          – total rows flagged FALSE
--   distinct_museums_in_fact     – distinct non-null museum_ids in fct_sales
-- ============================================================

SELECT
    -- Audit 1: Flag says TRUE but FK is null
    SUM(CASE WHEN fs.is_in_museum = TRUE  AND fs.museum_id IS NULL  THEN 1 ELSE 0 END)
                                                        AS flag_true_but_null_museum,

    -- Audit 2: Flag says FALSE but FK is populated
    SUM(CASE WHEN fs.is_in_museum = FALSE AND fs.museum_id IS NOT NULL THEN 1 ELSE 0 END)
                                                        AS flag_false_but_has_museum,

    -- Audit 3: fct_sales.museum_id vs dim_artwork.museum_id (should always match)
    SUM(CASE
            WHEN COALESCE(fs.museum_id::TEXT, 'NULL')
                 <> COALESCE(aw.museum_id::TEXT, 'NULL')
            THEN 1 ELSE 0
        END)                                            AS fact_museum_vs_artwork_mismatch,

    -- Informational counts
    SUM(CASE WHEN fs.is_in_museum = TRUE  THEN 1 ELSE 0 END)  AS total_in_museum,
    SUM(CASE WHEN fs.is_in_museum = FALSE THEN 1 ELSE 0 END)  AS total_not_in_museum,
    COUNT(DISTINCT fs.museum_id)                               AS distinct_museums_in_fact

FROM gold.fct_sales   fs
JOIN gold.dim_artwork aw ON fs.work_id = aw.work_id;