-- ============================================================================
-- Data Quality Check : Bronze Tables Not Empty
-- Purpose             : Ensures that every table in the bronze schema
--                       contains at least one record.
--
-- Validation Rule     : Bronze tables must NOT be empty.
--
-- Behavior            :
--   1. Iterates through all BASE TABLES in the bronze schema.
--   2. Counts rows in each table.
--   3. Raises a WARNING for every empty table.
--   4. Raises an EXCEPTION after checking all tables if any table is empty.
--   5. Raises a NOTICE for tables that pass the validation.
-- ============================================================================

DO $$
DECLARE
    tbl RECORD;
    row_count BIGINT;

    -- Stores the names of all empty Bronze tables
    empty_tables TEXT := '';
BEGIN

    -- ========================================================================
    -- Loop through every physical table in the bronze schema
    -- ========================================================================
    FOR tbl IN
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'bronze'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    LOOP

        -- ====================================================================
        -- Count the number of records in the current Bronze table
        -- ====================================================================
        EXECUTE format(
            'SELECT COUNT(*) FROM bronze.%I',
            tbl.table_name
        )
        INTO row_count;


        -- ====================================================================
        -- Validation: Table must contain at least one record
        -- ====================================================================
        IF row_count = 0 THEN

            -- Add the empty table to the failure list
            empty_tables := empty_tables || tbl.table_name || ', ';

            -- Log the failed validation
            RAISE WARNING
                'FAILED: Bronze table "%" is empty.',
                tbl.table_name;

        ELSE

            -- Log the successful validation
            RAISE NOTICE
                'PASSED: Bronze table "%" contains % rows.',
                tbl.table_name,
                row_count;

        END IF;

    END LOOP;


    -- ========================================================================
    -- Fail the data-quality check if one or more Bronze tables are empty
    -- ========================================================================
    IF empty_tables <> '' THEN

        RAISE EXCEPTION
            'Bronze Data Quality Check FAILED. Empty tables: %',
            RTRIM(empty_tables, ', ');

    END IF;


    -- ========================================================================
    -- All Bronze tables passed the validation
    -- ========================================================================
    RAISE NOTICE
        'Bronze Data Quality Check PASSED: No empty tables found.';

END $$;