-- C11 VIC source-model evidence queries.
--
-- Run each resource against the exact frozen Raw file identity.
-- These queries preserve native grains and avoid JOIN multiplication.


-- ============================================================
-- Q1. Accident-parent orphan checks
-- ============================================================

WITH accident AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'ACCIDENT_NO' AS accident_no
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

vehicle AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'ACCIDENT_NO' AS accident_no,
        r.payload ->> 'VEHICLE_ID' AS vehicle_id
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

person AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'ACCIDENT_NO' AS accident_no,
        r.payload ->> 'PERSON_ID' AS person_id,
        r.payload ->> 'VEHICLE_ID' AS vehicle_id
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

node AS (
    SELECT
        r.raw_record_id,
        r.payload ->> 'ACCIDENT_NO' AS accident_no,
        r.payload ->> 'NODE_ID' AS node_id
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
)

SELECT
    (
        SELECT COUNT(*)
        FROM vehicle AS v
        WHERE NOT EXISTS (
            SELECT 1
            FROM accident AS a
            WHERE a.accident_no = v.accident_no
        )
    ) AS vehicle_orphan_count,

    (
        SELECT COUNT(*)
        FROM person AS p
        WHERE NOT EXISTS (
            SELECT 1
            FROM accident AS a
            WHERE a.accident_no = p.accident_no
        )
    ) AS person_orphan_count,

    (
        SELECT COUNT(*)
        FROM node AS n
        WHERE NOT EXISTS (
            SELECT 1
            FROM accident AS a
            WHERE a.accident_no = n.accident_no
        )
    ) AS node_orphan_count;
