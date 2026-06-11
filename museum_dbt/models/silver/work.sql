{{ config(
    materialized='incremental',
    unique_key='work_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Duplicate_check AS (
    SELECT
        work_id,
        name,
        artist_id,
        style,
        museum_id,
        loaded_at,
        updated_at,
        ROW_NUMBER()
            OVER(PARTITION BY work_id
            ORDER BY updated_at DESC NULLS LAST) AS rnk
    FROM {{ source('bronze', 'work') }}
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
    WHERE work_id IS NOT NULL
      AND TRIM(work_id) != ''
      AND rnk = 1
)
SELECT
    NULLIF(TRIM(work_id), '')   :: NUMERIC :: INT  AS work_id,
    TRIM(name)                  :: VARCHAR(150)    AS name,
    NULLIF(TRIM(artist_id), '') :: NUMERIC :: INT  AS artist_id,
    NULLIF(TRIM(style), '')     :: VARCHAR(50)     AS style,
    NULLIF(TRIM(museum_id), '') :: NUMERIC :: INT  AS museum_id,
    updated_at                  :: TIMESTAMP       AS updated_at,
    loaded_at                   :: TIMESTAMP       AS loaded_at,
    CURRENT_TIMESTAMP                              AS silver_loaded_at
FROM Fixed