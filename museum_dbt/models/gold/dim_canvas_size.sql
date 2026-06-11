{{ config(
    materialized='table',
    tags=['gold', 'dimension']
) }}

WITH base AS (
    SELECT
        size_id,
        label,
        width_inches,
        height_inches,

        -- Computed area for BI sorting / sizing analysis
        CASE
            WHEN width_inches IS NOT NULL AND height_inches IS NOT NULL
                THEN ROUND((width_inches * height_inches)::NUMERIC, 2)
        END AS area_sq_inches,

        -- Bucketed size category for easy BI grouping
        CASE
            WHEN width_inches IS NULL OR height_inches IS NULL THEN 'Unknown'
            WHEN (width_inches * height_inches) <=  400        THEN 'Small'
            WHEN (width_inches * height_inches) <= 1600        THEN 'Medium'
            WHEN (width_inches * height_inches) <= 4000        THEN 'Large'
            ELSE                                               'Extra Large'
        END AS size_category

    FROM {{ ref('canvas_size') }}
    WHERE size_id IS NOT NULL
)

SELECT
    size_id,
    COALESCE(label, 'Unknown')  AS label,
    width_inches,
    height_inches,
    area_sq_inches,
    size_category
FROM base