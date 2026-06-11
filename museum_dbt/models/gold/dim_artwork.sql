{{ config(
    materialized='table',
    tags=['gold', 'dimension']
) }}

WITH artwork AS (
    SELECT
        work_id,
        name            AS artwork_name,
        style,
        artist_id,
        museum_id
    FROM {{ ref('work') }}
    WHERE work_id IS NOT NULL
),

subjects AS (
    SELECT
        work_id,
        STRING_AGG(subject, ',' ORDER BY subject) AS subject_tags
    FROM {{ ref('subject') }}
    GROUP BY work_id
)

SELECT
    a.work_id,
    a.artwork_name,
    NULLIF(TRIM(a.style), '')       AS style,
    COALESCE(s.subject_tags, 'Unknown') AS subject_tags,
    a.artist_id,
    a.museum_id
FROM artwork   a
LEFT JOIN subjects s ON a.work_id = s.work_id