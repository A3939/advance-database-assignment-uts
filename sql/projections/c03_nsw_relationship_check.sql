-- C03 NSW relationship checks.
-- These checks run on the complete frozen NSW Crash / Traffic Unit snapshot
-- before the 2020-2024 occurrence-year filter is applied.

WITH crash_rows AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'Crash ID' AS crash_id
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),
unit_rows AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'Crash ID' AS crash_id,
        r.payload ->> 'Traffic unit ID' AS traffic_unit_id
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),
crash_duplicates AS (
    SELECT crash_id
    FROM crash_rows
    WHERE crash_id IS NOT NULL
      AND btrim(crash_id) <> ''
    GROUP BY crash_id
    HAVING COUNT(*) > 1
),
unit_duplicates AS (
    SELECT crash_id, traffic_unit_id
    FROM unit_rows
    WHERE crash_id IS NOT NULL
      AND btrim(crash_id) <> ''
      AND traffic_unit_id IS NOT NULL
      AND btrim(traffic_unit_id) <> ''
    GROUP BY crash_id, traffic_unit_id
    HAVING COUNT(*) > 1
)
SELECT
    (
        SELECT COUNT(*)
        FROM crash_rows
        WHERE crash_id IS NULL
           OR btrim(crash_id) = ''
    ) AS crash_blank_key_count,

    (
        SELECT COUNT(*)
        FROM crash_duplicates
    ) AS crash_duplicate_key_count,

    (
        SELECT COUNT(*)
        FROM unit_rows
        WHERE crash_id IS NULL
           OR btrim(crash_id) = ''
           OR traffic_unit_id IS NULL
           OR btrim(traffic_unit_id) = ''
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
          AND btrim(u.crash_id) <> ''
          AND c.crash_id IS NULL
    ) AS orphan_unit_count;
