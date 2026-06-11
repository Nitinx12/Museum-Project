{{ config(
    materialized='incremental',
    unique_key='size_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Duplicate_check AS (
    SELECT
        size_id,
        width,
        height,
        label,
        loaded_at,
        updated_at,
        ROW_NUMBER()
            OVER(PARTITION BY size_id
            ORDER BY updated_at DESC NULLS LAST) AS rnk
    FROM {{ source('bronze', 'canvas_size') }}
),
Incremental_filter AS (
    SELECT *
    FROM Duplicate_check
    {% if is_incremental() %}
	WHERE COALESCE(updated_at, loaded_at)::timestamp >= 
		COALESCE(
			(SELECT MAX(updated_at::timestamp) FROM {{ this }}),
			TIMESTAMP '1900-01-01'
		) - INTERVAL '3 days'
    {% endif %}
),
Fixed AS (
    SELECT *
    FROM Incremental_filter
    WHERE size_id IS NOT NULL
      AND TRIM(size_id) != ''
      AND rnk = 1
)
SELECT
    NULLIF(TRIM(size_id), '')  :: INT          AS size_id,
    NULLIF(TRIM(width), '')    :: INT          AS width_inches,
    NULLIF(TRIM(height), '')   :: INT          AS height_inches,
    TRIM(label)                :: VARCHAR(100) AS label,
    updated_at                 :: TIMESTAMP    AS updated_at,
    loaded_at                  :: TIMESTAMP    AS loaded_at,
    CURRENT_TIMESTAMP                          AS silver_loaded_at
FROM Fixed