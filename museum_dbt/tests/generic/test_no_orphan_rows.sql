{#
    DRAFT — the uploaded file was empty, this is a starting point, not a
    confirmed implementation. Replace if you had different logic in mind.

    Fails one row per non-null {{ column_name }} value in `model` that has
    no matching value of `field` in `to`. NULLs in column_name are treated
    as "no relationship claimed" and are ignored, not flagged as orphans.

    This overlaps with dbt-core's built-in `relationships` test -- use this
    version if you want a distinct name/behavior (e.g. bundling it with your
    own generic-test conventions) rather than the built-in.

    Usage in schema.yml:
        - name: artist_id
          tests:
            - no_orphan_rows:
                to: ref('artist')
                field: artist_id
#}

{% test no_orphan_rows(model, column_name, to, field) %}

WITH child AS (
    SELECT {{ column_name }} AS fk_value
    FROM {{ model }}
    WHERE {{ column_name }} IS NOT NULL
),

parent AS (
    SELECT DISTINCT {{ field }} AS pk_value
    FROM {{ to }}
)

SELECT child.fk_value
FROM child
LEFT JOIN parent ON child.fk_value = parent.pk_value
WHERE parent.pk_value IS NULL

{% endtest %}