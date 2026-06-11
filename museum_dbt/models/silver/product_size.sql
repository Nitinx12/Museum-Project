{{ config(
    materialized='incremental',
    unique_key=['work_id', 'size_id'],
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

-- Cast and clean raw bronze values first, then deduplicate on the final
-- integer keys. The original order (deduplicate on text, cast after) caused
-- "MERGE cannot affect row a second time" because text variants like '1' and
-- '01' were treated as separate partitions by ROW_NUMBER() but resolved to the
-- same integer after casting, producing two source rows for one target key.

WITH Source AS (
    SELECT
        NULLIF(TRIM(work_id),       '')::NUMERIC::INT  AS work_id,
        NULLIF(TRIM(size_id),       '')::NUMERIC::INT  AS size_id,
        NULLIF(TRIM(sale_price),    '')::NUMERIC        AS sale_price,
        NULLIF(TRIM(regular_price), '')::NUMERIC        AS regular_price,
        COALESCE(updated_at, loaded_at)::TIMESTAMP      AS watermark,
        updated_at::TIMESTAMP                           AS updated_at,
        loaded_at::TIMESTAMP                            AS loaded_at
    FROM {{ source('bronze', 'product_size') }}
    WHERE work_id      IS NOT NULL
      AND size_id       IS NOT NULL
      AND TRIM(work_id)       NOT LIKE '#%'
      AND TRIM(size_id)       NOT LIKE '#%'
      AND TRIM(sale_price)    NOT LIKE '#%'
      AND TRIM(regular_price) NOT LIKE '#%'
),

Incremental_filter AS (
    SELECT *
    FROM Source
    {% if is_incremental() %}
    WHERE watermark >=
        COALESCE(
            (SELECT MAX(updated_at) FROM {{ this }}),
            TIMESTAMP '1900-01-01'
        ) - INTERVAL '3 days'
    {% endif %}
),

Deduplicated AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY work_id, size_id
            ORDER BY updated_at DESC NULLS LAST
        ) AS rnk
    FROM Incremental_filter
    WHERE work_id IS NOT NULL
      AND size_id  IS NOT NULL
)

SELECT
    work_id,
    size_id,
    sale_price,
    regular_price,
    updated_at,
    loaded_at,
    CURRENT_TIMESTAMP AS silver_loaded_at
FROM Deduplicated
WHERE rnk = 1