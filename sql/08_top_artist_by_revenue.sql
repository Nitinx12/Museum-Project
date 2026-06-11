-- ============================================================
-- Q08 · Top 10 Artists by Total Sale Revenue
-- Joins : fct_sales → dim_artist
-- Difficulty : Mid
-- ============================================================
-- PURPOSE
--   Rank artists by their commercial footprint (total sale revenue
--   across all artworks and size variants).  Includes era and
--   nationality context to spot patterns in top earners.
--
-- OUTPUT COLUMNS
--   revenue_rank         – dense rank by total_sale_revenue
--   artist_id
--   artist_name
--   nationality
--   era
--   artist_status        – Historical / Living / Unknown
--   style
--   artwork_count        – distinct works in fct_sales
--   sku_count            – total (work × size) rows
--   total_sale_revenue
--   total_regular_revenue
--   total_discount_given
--   avg_discount_pct
--   revenue_vs_next_pct  – % drop to the next-ranked artist
-- ============================================================

WITH artist_revenue AS (
    SELECT
        da.artist_id,
        da.artist_name,
        da.nationality,
        da.era,
        da.artist_status,
        da.style,
        COUNT(DISTINCT fs.work_id)              AS artwork_count,
        COUNT(*)                                AS sku_count,
        SUM(fs.sale_price)                      AS total_sale_revenue,
        SUM(fs.regular_price)                   AS total_regular_revenue,
        SUM(fs.discount_amount)                 AS total_discount_given,
        AVG(fs.discount_pct)                    AS avg_discount_pct
    FROM gold.fct_sales  fs
    JOIN gold.dim_artist da ON fs.artist_id = da.artist_id
    GROUP BY
        da.artist_id, da.artist_name, da.nationality,
        da.era, da.artist_status, da.style
)
SELECT
    DENSE_RANK() OVER (ORDER BY total_sale_revenue DESC NULLS LAST) AS revenue_rank,
    artist_id,
    artist_name,
    nationality,
    era,
    artist_status,
    style,
    artwork_count,
    sku_count,
    ROUND(total_sale_revenue::NUMERIC,   2)     AS total_sale_revenue,
    ROUND(total_regular_revenue::NUMERIC,2)     AS total_regular_revenue,
    ROUND(total_discount_given::NUMERIC, 2)     AS total_discount_given,
    ROUND(avg_discount_pct::NUMERIC,     2)     AS avg_discount_pct,
    ROUND(
        100.0 * (total_sale_revenue - LEAD(total_sale_revenue) OVER (ORDER BY total_sale_revenue DESC))
        / NULLIF(total_sale_revenue, 0),
    2)                                          AS revenue_vs_next_pct
FROM artist_revenue
ORDER BY total_sale_revenue DESC NULLS LAST
LIMIT 10;