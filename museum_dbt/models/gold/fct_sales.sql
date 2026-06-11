{{ config(
    materialized='table',
    tags=['gold', 'fact']
) }}

WITH product_raw AS (
    SELECT
        work_id,
        size_id,
        sale_price,
        regular_price,
        updated_at,
        ROW_NUMBER() OVER (
            PARTITION BY work_id, size_id
            ORDER BY updated_at DESC NULLS LAST
        ) AS rn
    FROM {{ ref('product_size') }}
    WHERE work_id IS NOT NULL
      AND size_id IS NOT NULL
),
product AS (
    SELECT work_id, size_id, sale_price, regular_price, updated_at
    FROM product_raw
    WHERE rn = 1
      AND size_id IN (SELECT size_id FROM {{ ref('dim_canvas_size') }})
),
artwork AS (
    SELECT
        work_id,
        artist_id,
        museum_id
    FROM {{ ref('dim_artwork') }}
),
final AS (
    SELECT
        -- Surrogate key: unique grain is (work_id, size_id)
        {{ dbt_utils.generate_surrogate_key(['p.work_id', 'p.size_id']) }}
                                                AS sales_key,

        -- Foreign keys
        p.work_id,
        a.artist_id,
        a.museum_id,
        p.size_id,

        -- Pricing measures
        p.sale_price,
        p.regular_price,

        -- Derived measures
        ROUND(
            (p.regular_price - p.sale_price)::NUMERIC, 2
        )                                       AS discount_amount,

        CASE
            WHEN p.regular_price IS NOT NULL
             AND p.regular_price > 0
                THEN ROUND(
                    ((p.regular_price - p.sale_price) / p.regular_price * 100)::NUMERIC
                    , 2)
        END                                     AS discount_pct,

        -- Availability flag (has a museum)
        CASE
            WHEN a.museum_id IS NOT NULL THEN TRUE
            ELSE FALSE
        END                                     AS is_in_museum,

        -- Audit
        p.updated_at                            AS source_updated_at,
        CURRENT_TIMESTAMP                       AS gold_loaded_at

    FROM product  p
    LEFT JOIN artwork a ON p.work_id = a.work_id
)
SELECT * FROM final