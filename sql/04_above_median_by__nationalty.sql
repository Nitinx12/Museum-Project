-- ============================================================
-- Q4 (High) | Share of artworks above median sale_price by nationality
-- Tables  : fct_sales, dim_artist
-- Columns : artist_id, sale_price, nationality
-- ============================================================

WITH global_median AS (
    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY sale_price) AS median_price
    FROM gold.fct_sales
    WHERE sale_price IS NOT NULL
),
nationality_stats AS (
    SELECT
        da.nationality,
        COUNT(fs.sales_key)                                         AS total_artworks,
        SUM(CASE WHEN fs.sale_price > gm.median_price THEN 1 ELSE 0 END)
                                                                    AS above_median_count,
        ROUND(
            (SUM(CASE WHEN fs.sale_price > gm.median_price THEN 1 ELSE 0 END) * 100.0)
            / NULLIF(COUNT(fs.sales_key), 0)
        , 2)                                                        AS pct_above_median,
        ROUND(AVG(fs.sale_price)::NUMERIC, 2)                       AS avg_sale_price
    FROM gold.fct_sales      fs
    JOIN gold.dim_artist     da ON fs.artist_id = da.artist_id
    CROSS JOIN global_median gm
    WHERE fs.sale_price IS NOT NULL
    GROUP BY da.nationality
)
SELECT
    nationality,
    total_artworks,
    above_median_count,
    pct_above_median,
    avg_sale_price
FROM nationality_stats
ORDER BY pct_above_median DESC;