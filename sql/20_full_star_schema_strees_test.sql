-- ============================================================
-- Q20 · Full Star-Schema Stress Test — Revenue Ranking with Percentiles
-- Joins : fct_sales → dim_artist → dim_artwork → dim_canvas_size → dim_museum
-- Difficulty : High  ★ Run this last; if it's correct, the whole model is solid
-- ============================================================
-- PURPOSE
--   The definitive end-to-end test.  For every (artist_era, size_category,
--   country) combination that has at least 5 fact rows, compute:
--   – Revenue and discount metrics
--   – Percentile ranks within each artist era
--   – Running revenue totals
--   – A classification of each combo as 'Top', 'Mid', or 'Tail'
--
--   If this query returns sensible, non-duplicated results with
--   correct window function values, your model joins and grain are
--   confirmed clean.
--
-- OUTPUT COLUMNS
--   artist_era, size_category, country
--   sku_count, distinct_artworks, distinct_artists, museum_count
--   total_sale_revenue, avg_sale_price, avg_discount_pct
--   revenue_rank_overall        – DENSE_RANK by total_sale_revenue
--   revenue_pct_rank_in_era     – PERCENT_RANK within the same artist_era
--   running_revenue_by_era      – cumulative sum within artist_era
--   revenue_tier                – 'Top 20%' / 'Mid 60%' / 'Tail 20%'
-- ============================================================

WITH base AS (
    SELECT
        da.era                          AS artist_era,
        cs.size_category,
        dm.country,
        fs.sales_key,
        fs.work_id,
        da.artist_id,
        dm.museum_id,
        fs.sale_price,
        fs.discount_pct
    FROM gold.fct_sales        fs
    JOIN gold.dim_artist       da ON fs.artist_id = da.artist_id
    JOIN gold.dim_artwork      aw ON fs.work_id   = aw.work_id   -- validates artwork FK
    JOIN gold.dim_canvas_size  cs ON fs.size_id   = cs.size_id
    LEFT JOIN gold.dim_museum  dm ON fs.museum_id = dm.museum_id
),
agg AS (
    SELECT
        artist_era,
        size_category,
        COALESCE(country, 'Unknown')             AS country,
        COUNT(*)                                 AS sku_count,
        COUNT(DISTINCT work_id)                  AS distinct_artworks,
        COUNT(DISTINCT artist_id)                AS distinct_artists,
        COUNT(DISTINCT museum_id)                AS museum_count,
        SUM(sale_price)                          AS total_sale_revenue,
        AVG(sale_price)                          AS avg_sale_price,
        AVG(discount_pct)                        AS avg_discount_pct
    FROM base
    GROUP BY artist_era, size_category, country
    HAVING COUNT(*) >= 5
),
ranked AS (
    SELECT
        *,
        -- Overall dense rank
        DENSE_RANK() OVER (ORDER BY total_sale_revenue DESC NULLS LAST)   AS revenue_rank_overall,

        -- Percent rank within era (0 = bottom, 1 = top)
        ROUND(
            PERCENT_RANK() OVER (
                PARTITION BY artist_era
                ORDER BY total_sale_revenue
            )::NUMERIC, 4
        )                                                                  AS revenue_pct_rank_in_era,

        -- Running total within era (ordered by revenue desc)
        ROUND(
            SUM(total_sale_revenue) OVER (
                PARTITION BY artist_era
                ORDER BY total_sale_revenue DESC
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            )::NUMERIC, 2
        )                                                                  AS running_revenue_by_era
    FROM agg
)
SELECT
    artist_era,
    size_category,
    country,
    sku_count,
    distinct_artworks,
    distinct_artists,
    museum_count,
    ROUND(total_sale_revenue::NUMERIC, 2)  AS total_sale_revenue,
    ROUND(avg_sale_price::NUMERIC,     2)  AS avg_sale_price,
    ROUND(avg_discount_pct::NUMERIC,   2)  AS avg_discount_pct,
    revenue_rank_overall,
    revenue_pct_rank_in_era,
    running_revenue_by_era,
    -- Classify tier based on pct rank within era
    CASE
        WHEN revenue_pct_rank_in_era >= 0.80 THEN 'Top 20%'
        WHEN revenue_pct_rank_in_era >= 0.20 THEN 'Mid 60%'
        ELSE                                      'Tail 20%'
    END                                   AS revenue_tier
FROM ranked
ORDER BY revenue_rank_overall;