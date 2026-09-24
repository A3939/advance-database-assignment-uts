-- C04 VIC Accident / Vehicle relationship checks.
--
-- IMPORTANT:
-- Run these checks against the complete frozen VIC Accident and Vehicle
-- snapshots BEFORE applying the 2020-2024 occurrence-date filter.
--
-- Vehicle identity:
--   ACCIDENT_NO + VEHICLE_ID
--
-- Parent relationship:
--   Vehicle.ACCIDENT_NO -> Accident.ACCIDENT_NO

WITH accident_rows AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

vehicle_rows AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no,
        r.payload ->> 'VEHICLE_ID'
            AS vehicle_id
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

accident_duplicates AS (
    SELECT
        accident_no
    FROM accident_rows
    WHERE accident_no IS NOT NULL
      AND btrim(accident_no) <> ''
    GROUP BY accident_no
    HAVING COUNT(*) > 1
),

vehicle_duplicates AS (
    SELECT
        accident_no,
        vehicle_id
    FROM vehicle_rows
    WHERE accident_no IS NOT NULL
      AND btrim(accident_no) <> ''
      AND vehicle_id IS NOT NULL
      AND btrim(vehicle_id) <> ''
    GROUP BY
        accident_no,
        vehicle_id
    HAVING COUNT(*) > 1
)

SELECT
    (
        SELECT COUNT(*)
        FROM accident_rows
        WHERE accident_no IS NULL
           OR btrim(accident_no) = ''
    ) AS accident_blank_key_count,

    (
        SELECT COUNT(*)
        FROM accident_duplicates
    ) AS accident_duplicate_key_count,

    (
        SELECT COUNT(*)
        FROM vehicle_rows
        WHERE accident_no IS NULL
           OR btrim(accident_no) = ''
           OR vehicle_id IS NULL
           OR btrim(vehicle_id) = ''
    ) AS vehicle_blank_key_count,

    (
        SELECT COUNT(*)
        FROM vehicle_duplicates
    ) AS vehicle_duplicate_key_count,

    (
        SELECT COUNT(*)
        FROM vehicle_rows AS v
        LEFT JOIN accident_rows AS a
          ON a.accident_no = v.accident_no
        WHERE v.accident_no IS NOT NULL
          AND btrim(v.accident_no) <> ''
          AND a.accident_no IS NULL
    ) AS orphan_vehicle_count;
