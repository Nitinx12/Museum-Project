-- ============================================================================
-- Whitespace Validation
-- Purpose:
--   Checks all character-based columns in the `silver` schema for:
--     1. Leading whitespace
--     2. Trailing whitespace
--
-- Example:
--   ' John'  -> INVALID
--   'John '  -> INVALID
--   ' John ' -> INVALID
--   'John'   -> VALID
--
-- Behavior:
--   - Loops through every TEXT / VARCHAR / CHAR column.
--   - Counts rows containing leading or trailing whitespace.
--   - Raises an exception when whitespace is found.
-- ============================================================================

DO $$
DECLARE

    -- Stores metadata for each text column
    r RECORD;

    -- Stores the number of rows containing whitespace
    whitespace_count BIGINT;

BEGIN

    -- ========================================================================
    -- Get all character columns from the silver schema
    -- ========================================================================
    FOR r IN
        SELECT
            table_schema,
            table_name,
            column_name
        FROM information_schema.columns
        WHERE table_schema = 'silver'
          AND data_type IN (
              'character varying',
              'character',
              'text'
          )
        ORDER BY
            table_name,
            ordinal_position

    LOOP

        -- ====================================================================
        -- Check for leading or trailing whitespace
        --
        -- BTRIM() removes whitespace from both sides.
        -- If the original value is different from BTRIM(value),
        -- the value contains leading or trailing whitespace.
        -- ====================================================================
        EXECUTE format(
            '
            SELECT COUNT(*)
            FROM %I.%I
            WHERE %I IS NOT NULL
              AND %I <> BTRIM(%I)
            ',
            r.table_schema,
            r.table_name,
            r.column_name,
            r.column_name,
            r.column_name
        )
        INTO whitespace_count;


        -- ====================================================================
        -- Raise exception if whitespace is detected
        -- ====================================================================
        IF whitespace_count > 0 THEN

            RAISE EXCEPTION
                'WHITESPACE VALIDATION FAILED | schema=%, table=%, column=%, affected_rows=%',
                r.table_schema,
                r.table_name,
                r.column_name,
                whitespace_count;

        END IF;


        -- ====================================================================
        -- Current column passed validation
        -- ====================================================================
        RAISE NOTICE
            'WHITESPACE CHECK PASSED | table=%, column=%',
            r.table_name,
            r.column_name;

    END LOOP;


    -- ========================================================================
    -- All text columns passed the whitespace validation
    -- ========================================================================
    RAISE NOTICE
        'WHITESPACE VALIDATION PASSED | schema=silver';

END $$;