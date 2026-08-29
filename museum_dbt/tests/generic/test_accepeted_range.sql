{#
    DRAFT — the uploaded file was empty, this is a starting point, not a
    confirmed implementation. Replace if you had different logic in mind.

    Fails one row per value outside [min_value, max_value]. NULLs are ignored
    (pair with a separate not_null test if NULLs should also fail). Bounds
    are inclusive by default.

    Usage in schema.yml:
        - accepted_range:
            min_value: 1000
            max_value: 2026
        - accepted_range:
            min_value: 0
            inclusive: false   # value must be strictly > min_value
#}

{% test accepeted_range(model, column_name, min_value=none, max_value=none, inclusive=true) %}

WITH validation AS (
    SELECT {{ column_name }} AS value_to_check
    FROM {{ model }}
    WHERE {{ column_name }} IS NOT NULL
)

SELECT value_to_check
FROM validation
WHERE
    {% if min_value is not none %}
        {% if inclusive %}
            value_to_check < {{ min_value }}
        {% else %}
            value_to_check <= {{ min_value }}
        {% endif %}
    {% else %}
        FALSE
    {% endif %}
    OR
    {% if max_value is not none %}
        {% if inclusive %}
            value_to_check > {{ max_value }}
        {% else %}
            value_to_check >= {{ max_value }}
        {% endif %}
    {% else %}
        FALSE
    {% endif %}

{% endtest %}