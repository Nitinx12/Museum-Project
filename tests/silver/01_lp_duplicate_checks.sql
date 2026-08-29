-- ============================================================================
-- Primary Key Duplicate Validation
-- Purpose:
--   Checks all PRIMARY KEY columns in the `silver` schema for duplicate values.
--
-- Behavior:
--   1. Finds every PRIMARY KEY defined in the `silver` schema.
--   2. Checks each primary key column for duplicate values.
--   3. Raises an exception if duplicates are found.
--   4. Stops execution immediately when a duplicate is detected.
--   5. Raises a success notice if all checks pass.
-- ============================================================================

DO $$
DECLARE
    r RECORD;
    duplicate_count BIGINT;
BEGIN
    FOR r IN
        SELECT
            kcu.table_schema,
            kcu.table_name,
            kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
            AND tc.table_name = kcu.table_name
        WHERE tc.constraint_type = 'PRIMARY KEY'
          AND tc.table_schema = 'silver'
    LOOP

        EXECUTE format(
            'SELECT COUNT(*)
             FROM (
                 SELECT %I
                 FROM %I.%I
                 GROUP BY %I
                 HAVING COUNT(*) > 1
             ) duplicates',
            r.column_name,
            r.table_schema,
            r.table_name,
            r.column_name
        )
        INTO duplicate_count;

        IF duplicate_count > 0 THEN
            RAISE EXCEPTION
                'Duplicate primary key found: schema=%, table=%, column=%, duplicate_groups=%',
                r.table_schema,
                r.table_name,
                r.column_name,
                duplicate_count;
        END IF;

    END LOOP;

    RAISE NOTICE 'Primary key duplicate check passed for silver schema.';
END $$;