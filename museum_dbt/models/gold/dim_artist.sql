{{ config(
    materialized='table',
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
)

SELECT
    artist_id,
    artist_name,
    COALESCE(nationality, 'Unknown') AS nationality,
    COALESCE(style, 'Unknown')       AS style,
    birth_year,
    death_year,
    era,
    artist_status
FROM base