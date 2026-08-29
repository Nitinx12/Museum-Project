{{ config(
    materialized='incremental',
    unique_key='work_id',
    incremental_strategy='merge',
    on_schema_change='append_new_columns',
    tags=['gold', 'dimension']
) }}

{% if is_incremental() %}
-- subject_tags is an aggregate across all of a work's subject rows, so a
-- work is "changed" if EITHER its own row changed OR any of its subject
-- rows changed. We collect the full set of affected work_ids here, then
-- recompute each one's aggregate from ALL of its subject rows below
-- (not just the ones that changed) so the STRING_AGG stays correct.
WITH changed_work_ids AS (
    SELECT work_id FROM {{ ref('work') }}
    WHERE silver_loaded_at > (
        COALESCE((SELECT MAX(silver_loaded_at) FROM {{ this }}), TIMESTAMP '1900-01-01')
        - INTERVAL '3 days'
    )
    UNION
    SELECT work_id FROM {{ ref('subject') }}
    WHERE silver_loaded_at > (
        COALESCE((SELECT MAX(silver_loaded_at) FROM {{ this }}), TIMESTAMP '1900-01-01')
        - INTERVAL '3 days'
    )
),
{% else %}
WITH
{% endif %}

artwork AS (
    SELECT
        work_id,
        name            AS artwork_name,
        style,
        artist_id,
        museum_id,
        silver_loaded_at
    FROM {{ ref('work') }}
    WHERE work_id IS NOT NULL
    {% if is_incremental() %}
      AND work_id IN (SELECT work_id FROM changed_work_ids)
    {% endif %}
),

subjects AS (
    SELECT
        work_id,
        STRING_AGG(subject, ',' ORDER BY subject) AS subject_tags
    FROM {{ ref('subject') }}
    {% if is_incremental() %}
      WHERE work_id IN (SELECT work_id FROM changed_work_ids)
    {% endif %}
    GROUP BY work_id
)

SELECT
    a.work_id,
    a.artwork_name,
    NULLIF(TRIM(a.style), '')       AS style,
    COALESCE(s.subject_tags, 'Unknown') AS subject_tags,
    a.artist_id,
    a.museum_id,
    a.silver_loaded_at,
    CURRENT_TIMESTAMP AS gold_loaded_at
FROM artwork   a
LEFT JOIN subjects s ON a.work_id = s.work_id