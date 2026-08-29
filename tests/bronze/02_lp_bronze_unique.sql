-- ============================================================================
-- Data Quality Check : _id + updated_at Uniqueness
-- Purpose             : Ensures that the combination of "_id" and "updated_at"
--                       is unique across every table in the bronze schema.
--
-- Validation Rules    :
--   1. "_id" must exist in the Bronze table.
--   2. "updated_at" must exist in the Bronze table.
--   3. The combination of "_id" and "updated_at" must be unique.
--
-- Behavior            :
--   1. Loops through all Bronze tables.
--   2. Checks whether required columns exist.
--   3. Detects duplicate "_id" + "updated_at" combinations.
--   4. Raises WARNING for failed tables.
--   5. Raises EXCEPTION after checking all tables if duplicates exist.
-- ============================================================================

DO $$
DECLARE
    tbl RECORD;
    duplicate_count BIGINT;
    empty_tables TEXT := '';
BEGIN

    -- ========================================================================
    -- Loop through all tables in the Bronze schema
    -- ========================================================================
    FOR tbl IN
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'bronze'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    LOOP

        -- ====================================================================
        -- Check whether "_id" and "updated_at" columns exist
        -- ====================================================================
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'bronze'
              AND table_name = tbl.table_name
              AND column_name = '_id'
        )
        OR NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'bronze'
              AND table_name = tbl.table_name
              AND column_name = 'updated_at'
        )
        THEN

            RAISE WARNING
                'SKIPPED: Bronze table "%" does not contain "_id" or "updated_at".',
                tbl.table_name;

            CONTINUE;
        END IF;


        -- ====================================================================
        -- Find duplicate "_id" + "updated_at" combinations
        -- ====================================================================
        EXECUTE format(
            'SELECT COUNT(*)
             FROM (
                 SELECT "_id", "updated_at"
                 FROM bronze.%I
                 GROUP BY "_id", "updated_at"
                 HAVING COUNT(*) > 1
             ) duplicates',
            tbl.table_name
        )
        INTO duplicate_count;


        -- ====================================================================
        -- Fail validation if duplicates are found
        -- ====================================================================
        IF duplicate_count > 0 THEN

            empty_tables := empty_tables
                || tbl.table_name
                || ' (' || duplicate_count || ' duplicate groups), ';

            RAISE WARNING
                'FAILED: Bronze table "%" contains % duplicate "_id" + "updated_at" combinations.',
                tbl.table_name,
                duplicate_count;

        ELSE

            -- Table passed uniqueness validation
            RAISE NOTICE
                'PASSED: Bronze table "%" has unique "_id" + "updated_at".',
                tbl.table_name;

        END IF;

    END LOOP;


    -- ========================================================================
    -- Raise exception if any table failed
    -- ========================================================================
    IF empty_tables <> '' THEN

        RAISE EXCEPTION
            'Bronze Data Quality Check FAILED. Duplicate "_id" + "updated_at": %',
            RTRIM(empty_tables, ', ');

    END IF;


    -- ========================================================================
    -- All applicable tables passed
    -- ========================================================================
    RAISE NOTICE
        'Bronze Data Quality Check PASSED: "_id" + "updated_at" are unique.';

END $$;