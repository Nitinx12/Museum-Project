{{ config(
    materialized='incremental',
    unique_key='artist_id',
    incremental_strategy='merge',
    on_schema_change='sync_all_columns'
) }}

WITH Duplicate_check AS(
	SELECT
		artist_id,
		first_name,
		middle_names,
		last_name,
		nationality,
		style,
		birth,
		death,
		loaded_at,
		updated_at,
		ROW_NUMBER()
			OVER(PARTITION BY artist_id
			ORDER BY updated_at DESC NULLS LAST) AS rnk
	FROM {{ source('bronze', 'artist') }}
),
Incremental_filter AS(
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
Fixed AS(
	SELECT *
	FROM Incremental_filter
	WHERE artist_id IS NOT NULL AND rnk = 1
)
SELECT
	TRIM(artist_id) :: INT AS artist_id,
	TRIM(
	    CONCAT_WS(
	        ' ',
	        NULLIF(TRIM(first_name), ''),
	        NULLIF(TRIM(middle_names), ''),
	        NULLIF(TRIM(last_name), '')
	    )
	)::VARCHAR(75) AS artist_name,
	TRIM(nationality) :: VARCHAR(50) AS nationality,
	TRIM(style) :: VARCHAR(50) AS style,
	TRIM(birth) :: INT AS birth_year,
	TRIM(death) :: INT AS death_year,
	updated_at :: TIMESTAMP AS updated_at,
	loaded_at :: TIMESTAMP AS loaded_at,
	CURRENT_TIMESTAMP AS silver_loaded_at
FROM Fixed