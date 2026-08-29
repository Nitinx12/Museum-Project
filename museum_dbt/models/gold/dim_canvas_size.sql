{{ config(
    materialized='incremental',
    unique_key='size_id',
    incremental_strategy='merge',
    on_schema_change='append_new_columns',
    tags=['gold', 'dimension']
) }}

WITH base AS (
    SELECT
        size_id,
        label,
        width_inches,
        height_inches,
        silver_loaded_at,

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

    {% if is_incremental() %}
      AND silver_loaded_at > (
          COALESCE((SELECT MAX(silver_loaded_at) FROM {{ this }}), TIMESTAMP '1900-01-01')
          - INTERVAL '3 days'
      )
    {% endif %}
)

SELECT
    size_id,
    COALESCE(label, 'Unknown')  AS label,
    width_inches,
    height_inches,
    area_sq_inches,
    size_category,
    silver_loaded_at,
    CURRENT_TIMESTAMP AS gold_loaded_at
FROM base