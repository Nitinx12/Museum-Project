-- ============================================================================
-- PRIMARY KEY DATA QUALITY VALIDATION
-- ============================================================================
-- Purpose:
--   Validates all PRIMARY KEY columns in the `silver` schema.
--
-- Rules:
--   1. PRIMARY KEY cannot contain NULL values.
--   2. PRIMARY KEY values must be unique.
--
-- Behavior:
--   - Dynamically finds PRIMARY KEY columns.
--   - Checks NULL values.
--   - Checks duplicate values.
--   - Raises an exception when a validation fails.
--   - Prints a NOTICE when a PRIMARY KEY passes validation.
-- ============================================================================

DO $$
DECLARE

    -- Stores PRIMARY KEY metadata
    r RECORD;

    -- Stores number of NULL values
    null_count BIGINT;

    -- Stores number of duplicate PRIMARY KEY groups
    duplicate_count BIGINT;

BEGIN

    -- ========================================================================
    -- Get all PRIMARY KEY columns from the silver schema
    -- ========================================================================
    FOR r IN
        SELECT
            kcu.table_schema,
            kcu.table_name,
            kcu.column_name
        FROM information_schema.table_constraints AS tc

        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
            AND tc.table_name = kcu.table_name

        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = 'silver'

        ORDER BY
            kcu.table_name,
            kcu.ordinal_position

    LOOP

        -- ====================================================================
        -- CHECK 1: PRIMARY KEY NULL VALUES
        -- ====================================================================
        EXECUTE format(
            '
            SELECT COUNT(*)
            FROM %I.%I
            WHERE %I IS NULL
            ',
            r.table_schema,
            r.table_name,
            r.column_name
        )
        INTO null_count;


        -- ====================================================================
        -- Raise exception if NULL PRIMARY KEY values are found
        -- ====================================================================
        IF null_count > 0 THEN

            RAISE EXCEPTION
                'PRIMARY KEY NULL VALIDATION FAILED | schema=%, table=%, column=%, null_rows=%',
                r.table_schema,
                r.table_name,
                r.column_name,
                null_count;

        END IF;


        -- ====================================================================
        -- CHECK 2: PRIMARY KEY DUPLICATES
        -- ====================================================================
        EXECUTE format(
            '
            SELECT COUNT(*)
            FROM (
                SELECT %I
                FROM %I.%I
                GROUP BY %I
                HAVING COUNT(*) > 1
            ) AS duplicates
            ',
            r.column_name,
            r.table_schema,
            r.table_name,
            r.column_name
        )
        INTO duplicate_count;


        -- ====================================================================
        -- Raise exception if duplicate PRIMARY KEY values are found
        -- ====================================================================
        IF duplicate_count > 0 THEN

            RAISE EXCEPTION
                'PRIMARY KEY DUPLICATE VALIDATION FAILED | schema=%, table=%, column=%, duplicate_groups=%',
                r.table_schema,
                r.table_name,
                r.column_name,
                duplicate_count;

        END IF;


        -- ====================================================================
        -- PRIMARY KEY passed both validations
        -- ====================================================================
        RAISE NOTICE
            'PRIMARY KEY CHECK PASSED | table=%, column=%',
            r.table_name,
            r.column_name;

    END LOOP;


    -- ========================================================================
    -- All PRIMARY KEY validations passed
    -- ========================================================================
    RAISE NOTICE
        'PRIMARY KEY VALIDATION PASSED | schema=silver';

END $$;