-- C03 NSW relationship checks.
-- These checks run on the complete frozen NSW Crash / Traffic Unit snapshot
-- before the manifest occurrence-year filter is applied.

WITH crash_rows AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'Crash ID' AS crash_id
    FROM pg_temp.c03_nsw_crash AS r
    WHERE r.source_id = %(source_id)s
      AND r.resource_id = %(crash_resource_id)s
      AND r.file_sha256 = %(crash_file_sha256)s
      AND r.parser_version = %(crash_parser_version)s
),
unit_rows AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'Crash ID' AS crash_id,
        r.payload ->> 'Traffic unit ID' AS traffic_unit_id
    FROM pg_temp.c03_nsw_unit AS r
    WHERE r.source_id = %(source_id)s
      AND r.resource_id = %(unit_resource_id)s
      AND r.file_sha256 = %(unit_file_sha256)s
      AND r.parser_version = %(unit_parser_version)s
),
crash_duplicates AS (
    SELECT crash_id
    FROM crash_rows
    WHERE crash_id IS NOT NULL
      AND btrim(crash_id, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000') <> ''
    GROUP BY crash_id
    HAVING COUNT(*) > 1
),
unit_duplicates AS (
    SELECT crash_id, traffic_unit_id
    FROM unit_rows
    WHERE crash_id IS NOT NULL
      AND btrim(crash_id, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000') <> ''
      AND traffic_unit_id IS NOT NULL
      AND btrim(traffic_unit_id, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000') <> ''
    GROUP BY crash_id, traffic_unit_id
    HAVING COUNT(*) > 1
)
SELECT
    (
        SELECT COUNT(*)
        FROM crash_rows
        WHERE crash_id IS NULL
           OR btrim(crash_id, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000') = ''
    ) AS crash_blank_key_count,

    (
        SELECT COUNT(*)
        FROM crash_duplicates
    ) AS crash_duplicate_key_count,

    (
        SELECT COUNT(*)
        FROM unit_rows
        WHERE crash_id IS NULL
           OR btrim(crash_id, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000') = ''
           OR traffic_unit_id IS NULL
           OR btrim(traffic_unit_id, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000') = ''
    ) AS unit_blank_key_count,

    (
        SELECT COUNT(*)
        FROM unit_duplicates
    ) AS unit_duplicate_key_count,

    (
        SELECT COUNT(*)
        FROM unit_rows AS u
        LEFT JOIN crash_rows AS c
          ON c.crash_id = u.crash_id
        WHERE u.crash_id IS NOT NULL
          AND btrim(u.crash_id, U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000') <> ''
          AND c.crash_id IS NULL
    ) AS orphan_unit_count;
