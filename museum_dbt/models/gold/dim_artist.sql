{{ config(
    materialized='incremental',
    unique_key='artist_id',
    incremental_strategy='merge',
    on_schema_change='append_new_columns',
    tags=['gold', 'dimension']
) }}

WITH base AS (
    SELECT
        artist_id,
        artist_name,
        nationality,
        style,
        birth_year,
        death_year,
        silver_loaded_at,

        -- Classify artist era based on birth_year for BI slicing
        CASE
            WHEN birth_year IS NULL          THEN 'Unknown'
            WHEN birth_year < 1400           THEN 'Medieval & Earlier'
            WHEN birth_year BETWEEN 1400 AND 1599 THEN 'Renaissance'
            WHEN birth_year BETWEEN 1600 AND 1749 THEN 'Baroque & Rococo'
            WHEN birth_year BETWEEN 1750 AND 1849 THEN 'Neoclassical & Romantic'
            WHEN birth_year BETWEEN 1850 AND 1899 THEN 'Impressionist Era'
            WHEN birth_year BETWEEN 1900 AND 1949 THEN 'Modern'
            ELSE                                  'Contemporary'
        END AS era,

        -- Flag whether the artist is historical (deceased) or living
        CASE
            WHEN death_year IS NOT NULL THEN 'Historical'
            ELSE 'Living / Unknown'
        END AS artist_status

    FROM {{ ref('artist') }}
    WHERE artist_id IS NOT NULL

    {% if is_incremental() %}
      -- Only pull rows touched since our last load, with a 3-day buffer
      -- to catch late-arriving corrections to already-loaded silver rows
      AND silver_loaded_at > (
          COALESCE((SELECT MAX(silver_loaded_at) FROM {{ this }}), TIMESTAMP '1900-01-01')
          - INTERVAL '3 days'
      )
    {% endif %}
)

SELECT
    artist_id,
    artist_name,
    COALESCE(nationality, 'Unknown') AS nationality,
    COALESCE(style, 'Unknown')       AS style,
    birth_year,
    death_year,
    era,
    artist_status,
    silver_loaded_at,
    CURRENT_TIMESTAMP AS gold_loaded_at
FROM base