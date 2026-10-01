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


-- ============================================================
-- Q2. Non-empty Person -> Vehicle references that do not match
-- ============================================================

WITH vehicle AS (
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
        r.row_locator,
        r.payload ->> 'ACCIDENT_NO' AS accident_no,
        r.payload ->> 'PERSON_ID' AS person_id,
        r.payload ->> 'VEHICLE_ID' AS vehicle_id,
        r.payload ->> 'ROAD_USER_TYPE' AS road_user_type,
        r.payload ->> 'SEATING_POSITION' AS seating_position
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
)

SELECT
    p.raw_record_id,
    p.row_locator,
    p.accident_no,
    p.person_id,
    p.vehicle_id,
    p.road_user_type,
    p.seating_position

FROM person AS p

WHERE p.vehicle_id IS NOT NULL
  AND p.vehicle_id <> ''

  AND NOT EXISTS (
      SELECT 1
      FROM vehicle AS v
      WHERE v.accident_no = p.accident_no
        AND v.vehicle_id = p.vehicle_id
  )

ORDER BY
    p.accident_no,
    p.person_id;

-- ============================================================
-- Q3A. Exact duplicate Node observations
-- ============================================================

WITH node AS (
    SELECT
        r.raw_record_id,
        r.row_locator,
        r.payload
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

duplicate_payloads AS (
    SELECT
        payload,
        COUNT(*) AS observation_count
    FROM node
    GROUP BY payload
    HAVING COUNT(*) > 1
)

SELECT
    COUNT(*) AS duplicate_group_count,

    COALESCE(
        SUM(observation_count - 1),
        0
    ) AS duplicate_extra_row_count

FROM duplicate_payloads;

-- ============================================================
-- Q3B. Repeated ACCIDENT_NO + NODE_ID observation groups
-- ============================================================

WITH node AS (
    SELECT
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no,

        r.payload ->> 'NODE_ID'
            AS node_id

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
)

SELECT
    accident_no,
    node_id,
    COUNT(*) AS observation_count

FROM node

GROUP BY
    accident_no,
    node_id

HAVING COUNT(*) > 1

ORDER BY
    observation_count DESC,
    accident_no,
    node_id;

-- ============================================================
-- Q3C. Node groups where only DEG_URBAN_NAME differs
-- ============================================================

WITH node AS (
    SELECT
        r.payload - 'DEG_URBAN_NAME'
            AS payload_without_deg_urban,

        r.payload ->> 'DEG_URBAN_NAME'
            AS deg_urban_name

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

varying_groups AS (
    SELECT
        payload_without_deg_urban,
        COUNT(DISTINCT deg_urban_name)
            AS distinct_deg_urban_names,
        COUNT(*) AS observation_count

    FROM node

    GROUP BY payload_without_deg_urban

    HAVING COUNT(DISTINCT deg_urban_name) > 1
)

SELECT
    COUNT(*) AS groups_varying_only_deg_urban_name,
    COALESCE(
        SUM(observation_count),
        0
    ) AS observations_in_those_groups

FROM varying_groups;

-- ============================================================
-- Q4. Node coordinate validity and conflict groups
-- ============================================================

WITH node AS (
    SELECT
        r.raw_record_id,

        r.payload ->> 'ACCIDENT_NO'
            AS accident_no,

        r.payload ->> 'NODE_ID'
            AS node_id,

        r.payload ->> 'LATITUDE'
            AS latitude_raw,

        r.payload ->> 'LONGITUDE'
            AS longitude_raw

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

parsed AS (
    SELECT
        *,

        CASE
            WHEN latitude_raw IS NOT NULL
             AND btrim(latitude_raw) <> ''
             AND pg_input_is_valid(
                    latitude_raw,
                    'numeric'
                 )
            THEN latitude_raw::numeric
            ELSE NULL
        END AS latitude_value,

        CASE
            WHEN longitude_raw IS NOT NULL
             AND btrim(longitude_raw) <> ''
             AND pg_input_is_valid(
                    longitude_raw,
                    'numeric'
                 )
            THEN longitude_raw::numeric
            ELSE NULL
        END AS longitude_value

    FROM node
),

classified AS (
    SELECT
        *,

        (
            latitude_value IS NOT NULL
            AND longitude_value IS NOT NULL
            AND latitude_value BETWEEN -90 AND 90
            AND longitude_value BETWEEN -180 AND 180
        ) AS coordinate_valid

    FROM parsed
),

grouped AS (
    SELECT
        accident_no,
        node_id,

        COUNT(*) AS observation_count,

        COUNT(*) FILTER (
            WHERE NOT coordinate_valid
        ) AS invalid_observation_count,

        COUNT(
            DISTINCT (
                latitude_value,
                longitude_value
            )
        ) FILTER (
            WHERE coordinate_valid
        ) AS valid_coordinate_pair_count

    FROM classified

    GROUP BY
        accident_no,
        node_id
)

SELECT
    COUNT(*) FILTER (
        WHERE invalid_observation_count > 0
    ) AS invalid_coordinate_group_count,

    COUNT(*) FILTER (
        WHERE valid_coordinate_pair_count > 1
    ) AS coordinate_conflict_group_count,

    COUNT(*) FILTER (
        WHERE invalid_observation_count = 0
          AND valid_coordinate_pair_count = 1
    ) AS single_coordinate_pair_group_count

FROM grouped;

-- ============================================================
-- Q5A. Safe JOIN-multiplication diagnostic
-- ============================================================

WITH vehicle_counts AS (
    SELECT
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no,
        COUNT(*) AS vehicle_count

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s

    GROUP BY
        r.payload ->> 'ACCIDENT_NO'
),

person_counts AS (
    SELECT
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no,
        COUNT(*) AS person_count

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s

    GROUP BY
        r.payload ->> 'ACCIDENT_NO'
),

node_counts AS (
    SELECT
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no,
        COUNT(*) AS node_observation_count

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s

    GROUP BY
        r.payload ->> 'ACCIDENT_NO'
),

all_accidents AS (
    SELECT accident_no FROM vehicle_counts
    UNION
    SELECT accident_no FROM person_counts
    UNION
    SELECT accident_no FROM node_counts
)

SELECT
    a.accident_no,

    COALESCE(
        v.vehicle_count,
        0
    ) AS vehicle_count,

    COALESCE(
        p.person_count,
        0
    ) AS person_count,

    COALESCE(
        n.node_observation_count,
        0
    ) AS node_observation_count,

    GREATEST(
        COALESCE(v.vehicle_count, 0),
        1
    )
    *
    GREATEST(
        COALESCE(p.person_count, 0),
        1
    )
    *
    GREATEST(
        COALESCE(n.node_observation_count, 0),
        1
    ) AS rows_from_naive_multi_join

FROM all_accidents AS a

LEFT JOIN vehicle_counts AS v
  ON v.accident_no = a.accident_no

LEFT JOIN person_counts AS p
  ON p.accident_no = a.accident_no

LEFT JOIN node_counts AS n
  ON n.accident_no = a.accident_no

ORDER BY
    rows_from_naive_multi_join DESC,
    a.accident_no

LIMIT 50;

-- ============================================================
-- Q5B. Actual naive JOIN for one selected Accident
--
-- Final parameter = native ACCIDENT_NO to demonstrate.
-- ============================================================

WITH accident AS (
    SELECT
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
      AND r.payload ->> 'ACCIDENT_NO' = %s
),

vehicle AS (
    SELECT
        r.raw_record_id AS vehicle_raw_record_id,
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

person AS (
    SELECT
        r.raw_record_id AS person_raw_record_id,
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no,
        r.payload ->> 'PERSON_ID'
            AS person_id

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
),

node AS (
    SELECT
        r.raw_record_id AS node_raw_record_id,
        r.payload ->> 'ACCIDENT_NO'
            AS accident_no,
        r.payload ->> 'NODE_ID'
            AS node_id

    FROM raw.record AS r

    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
)

SELECT
    a.accident_no,
    v.vehicle_id,
    p.person_id,
    n.node_id,
    v.vehicle_raw_record_id,
    p.person_raw_record_id,
    n.node_raw_record_id

FROM accident AS a

LEFT JOIN vehicle AS v
  ON v.accident_no = a.accident_no

LEFT JOIN person AS p
  ON p.accident_no = a.accident_no

LEFT JOIN node AS n
  ON n.accident_no = a.accident_no

ORDER BY
    v.vehicle_id,
    p.person_id,
    n.node_raw_record_id;


-- Q0. Native keys: physical rows, blank keys and repeated key groups.
WITH selected AS (
  SELECT r.*, f.entity_kind
  FROM jsonb_to_recordset(%s::jsonb) f(source_id text, resource_id text,
       file_sha256 text, parser_version text, entity_kind text)
  JOIN raw.record r USING (source_id, resource_id, file_sha256, parser_version)
), keyed AS (
  SELECT *, CASE entity_kind
    WHEN 'crash' THEN jsonb_build_array(payload->>'ACCIDENT_NO')
    WHEN 'unit' THEN jsonb_build_array(payload->>'ACCIDENT_NO',payload->>'VEHICLE_ID')
    WHEN 'person_raw' THEN jsonb_build_array(payload->>'ACCIDENT_NO',payload->>'PERSON_ID')
    WHEN 'node_raw' THEN jsonb_build_array(payload->>'ACCIDENT_NO',payload->>'NODE_ID') END AS native_key
  FROM selected
), groups AS (
  SELECT resource_id,native_key,count(*) n FROM keyed GROUP BY resource_id,native_key
)
SELECT k.resource_id,count(*) AS raw_count,
 count(*) FILTER (WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(k.native_key) v
                               WHERE v IS NULL OR btrim(v)='')) AS blank_key_rows,
 (SELECT count(*) FROM groups g WHERE g.resource_id=k.resource_id AND n>1) AS duplicate_key_groups,
 (SELECT coalesce(sum(n-1),0) FROM groups g WHERE g.resource_id=k.resource_id AND n>1) AS duplicate_extra_rows
FROM keyed k GROUP BY k.resource_id ORDER BY k.resource_id;

-- Q2B. Exact native empty, NULL and whitespace-only vehicle references differ.
WITH person AS (
 SELECT payload FROM raw.record WHERE source_id=%s AND resource_id=%s
 AND file_sha256=%s AND parser_version=%s
)
SELECT count(*) AS person_rows,
 count(*) FILTER (WHERE payload->>'VEHICLE_ID'='') AS empty_vehicle_refs,
 count(*) FILTER (WHERE payload->>'VEHICLE_ID' IS NULL) AS null_vehicle_refs,
 count(*) FILTER (WHERE payload->>'VEHICLE_ID'<>'' AND btrim(payload->>'VEHICLE_ID')='') AS space_only_vehicle_refs,
 count(*) FILTER (WHERE payload->>'VEHICLE_ID'='' AND payload->>'ROAD_USER_TYPE'='1'
                   AND payload->>'SEATING_POSITION'='NA') AS registered_pedestrian_nonassociation,
 count(*) FILTER (WHERE payload->>'VEHICLE_ID'='' AND NOT
   (payload->>'ROAD_USER_TYPE'='1' AND payload->>'SEATING_POSITION'='NA')) AS other_empty_refs
FROM person;

-- Q5C. Person-to-Vehicle join uses both key fields and preserves Person grain.
WITH vehicle AS (
 SELECT payload FROM raw.record WHERE source_id=%s AND resource_id=%s
 AND file_sha256=%s AND parser_version=%s
), person AS (
 SELECT raw_record_id,payload FROM raw.record WHERE source_id=%s AND resource_id=%s
 AND file_sha256=%s AND parser_version=%s
), matched AS (
 SELECT p.raw_record_id,count(v.payload) matches FROM person p LEFT JOIN vehicle v
 ON p.payload->>'ACCIDENT_NO'=v.payload->>'ACCIDENT_NO'
 AND p.payload->>'VEHICLE_ID'=v.payload->>'VEHICLE_ID'
 AND p.payload->>'VEHICLE_ID' IS NOT NULL AND p.payload->>'VEHICLE_ID'<>''
 GROUP BY p.raw_record_id
)
SELECT count(*) AS person_rows,coalesce(sum(greatest(matches,1)),0) AS joined_rows,
 count(*) FILTER (WHERE matches>1) AS multiplied_person_rows,
 count(*) FILTER (WHERE matches=1) AS matched_person_rows,
 count(*) FILTER (WHERE matches=0) AS unmatched_or_nonassociated_rows FROM matched;

-- Q6. Accident/Node matching uses the complete pair; retain missing observations.
WITH accident AS (
 SELECT raw_record_id,row_locator,payload FROM raw.record WHERE source_id=%s AND resource_id=%s
 AND file_sha256=%s AND parser_version=%s
), node AS (
 SELECT payload FROM raw.record WHERE source_id=%s AND resource_id=%s
 AND file_sha256=%s AND parser_version=%s
)
SELECT a.raw_record_id,a.row_locator,a.payload->>'ACCIDENT_NO' accident_no,
 a.payload->>'NODE_ID' node_id,a.payload->>'ACCIDENT_DATE' accident_date
FROM accident a WHERE NOT EXISTS (
 SELECT 1 FROM node n WHERE n.payload->>'ACCIDENT_NO'=a.payload->>'ACCIDENT_NO'
 AND n.payload->>'NODE_ID'=a.payload->>'NODE_ID') ORDER BY a.row_locator;
