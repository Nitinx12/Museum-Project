-- ============================================================
-- Q13 · Discount Derivation & discount_pct Accuracy Audit  ← SINGLE TABLE
-- Joins : fct_sales only
-- Difficulty : High
-- ============================================================
-- PURPOSE
--   Precisely audit the two derived measures in fct_sales:
--     • discount_amount = ROUND(regular_price - sale_price, 2)
--     • discount_pct    = ROUND((regular_price - sale_price) / regular_price * 100, 2)
--   Also checks for business-logic anomalies:
--     • sale_price > regular_price (negative discount)
--     • discount_pct stored as NULL when it should be computable
--     • rows where discount_amount <> 0 but discount_pct IS NULL
--
-- OUTPUT COLUMNS (summary row)
--   total_rows
--   discount_amount_mismatches   – stored vs recomputed differ > 0.02
--   discount_pct_mismatches      – stored vs recomputed differ > 0.02
--   negative_discount_rows       – sale_price > regular_price
--   orphan_pct_null_rows         – discount_amount ≠ 0 but pct is NULL
--   zero_price_rows              – regular_price = 0 or NULL (pct undefined)
--   rows_with_no_discount        – discount_pct = 0 or NULL
-- ============================================================

SELECT
    COUNT(*)                                                            AS total_rows,

    -- discount_amount accuracy
    SUM(
        CASE
            WHEN ABS(
                COALESCE(discount_amount, 0)
                - ROUND((COALESCE(regular_price, 0) - COALESCE(sale_price, 0))::NUMERIC, 2)
            ) > 0.02
            THEN 1 ELSE 0
        END
    )                                                                   AS discount_amount_mismatches,

    -- discount_pct accuracy (only validate where regular_price > 0)
    SUM(
        CASE
            WHEN regular_price > 0
             AND ABS(
                    COALESCE(discount_pct, 0)
                    - ROUND(((regular_price - sale_price) / regular_price * 100)::NUMERIC, 2)
                 ) > 0.02
            THEN 1 ELSE 0
        END
    )                                                                   AS discount_pct_mismatches,

    -- Negative discounts (sale > regular)
    SUM(CASE WHEN sale_price > regular_price THEN 1 ELSE 0 END)        AS negative_discount_rows,

    -- discount_pct is NULL but discount_amount is non-zero (orphan)
    SUM(
        CASE WHEN discount_pct IS NULL
              AND COALESCE(discount_amount, 0) <> 0
             THEN 1 ELSE 0 END
    )                                                                   AS orphan_pct_null_rows,

    -- regular_price is NULL or 0 (makes pct undefined, expected to be NULL)
    SUM(CASE WHEN COALESCE(regular_price, 0) = 0 THEN 1 ELSE 0 END)   AS zero_price_rows,

    -- No discount at all
    SUM(CASE WHEN COALESCE(discount_pct, 0) = 0 THEN 1 ELSE 0 END)    AS rows_with_no_discount

FROM gold.fct_sales;