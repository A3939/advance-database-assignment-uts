/*
C06 — VIC Person Relationships and Count Checks

Check C06-01:
Detect duplicate candidate Person keys.

Candidate Person key:
    ACCIDENT_NO + PERSON_ID

This query is read-only.
It does not create, update or repair any source records.
*/

WITH person_raw AS (
    SELECT
        raw_record_id,
        row_locator,
        payload ->> 'ACCIDENT_NO' AS accident_no,
        payload ->> 'PERSON_ID' AS person_id
    FROM raw.record
    WHERE source_id = 'official_vic'
      AND resource_id = 'official_vic_person'
      AND file_sha256 =
          '71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9'
      AND parser_version = 'csv-native-v1'
),

duplicate_person_keys AS (
    SELECT
        accident_no,
        person_id,
        COUNT(*) AS duplicate_count,
        ARRAY_AGG(raw_record_id) AS raw_record_ids,
        ARRAY_AGG(row_locator) AS row_locators
    FROM person_raw
    GROUP BY
        accident_no,
        person_id
    HAVING COUNT(*) > 1
)

SELECT
    'duplicate_person_key' AS diagnostic_code,
    accident_no,
    person_id,
    duplicate_count,
    raw_record_ids,
    row_locators
FROM duplicate_person_keys
ORDER BY
    accident_no,
    person_id;


/*
C06-02 — Person → Accident parent check

Each VIC Person row must reference a real Accident through ACCIDENT_NO.

Rules:
- blank/whitespace ACCIDENT_NO is invalid;
- nonblank ACCIDENT_NO must match the full Accident resource;
- do not create an artificial Accident parent;
- retain Raw lineage for diagnostics.
*/

WITH person_raw AS (
    SELECT
        raw_record_id,
        row_locator,
        payload ->> 'ACCIDENT_NO' AS accident_no,
        payload ->> 'PERSON_ID' AS person_id,
        payload ->> 'VEHICLE_ID' AS vehicle_id
    FROM raw.record
    WHERE source_id = 'official_vic'
      AND resource_id = 'official_vic_person'
      AND file_sha256 =
          '71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9'
      AND parser_version = 'csv-native-v1'
),

accident_raw AS (
    SELECT
        raw_record_id AS accident_raw_record_id,
        row_locator AS accident_row_locator,
        payload ->> 'ACCIDENT_NO' AS accident_no
    FROM raw.record
    WHERE source_id = 'official_vic'
      AND resource_id = 'official_vic_accident'
      AND file_sha256 =
          'a148c00601fab10d44368df80492c594123700a7f9e334ff896fd215295e91d9'
      AND parser_version = 'csv-native-v1'
),

person_parent_check AS (
    SELECT
        p.raw_record_id,
        p.row_locator,
        p.accident_no,
        p.person_id,
        p.vehicle_id,
        a.accident_raw_record_id,
        CASE
            WHEN p.accident_no IS NULL
                 OR btrim(p.accident_no) = ''
                THEN 'blank_accident_parent_key'

            WHEN a.accident_raw_record_id IS NULL
                THEN 'missing_accident_parent'

            ELSE NULL
        END AS diagnostic_code
    FROM person_raw p
    LEFT JOIN accident_raw a
        ON p.accident_no = a.accident_no
)

SELECT
    diagnostic_code,
    raw_record_id,
    row_locator,
    accident_no,
    person_id,
    vehicle_id
FROM person_parent_check
WHERE diagnostic_code IS NOT NULL
ORDER BY
    accident_no,
    person_id;


/*
C06-03 — Person → Vehicle relationship check

For every Person row with a non-empty VEHICLE_ID:

    Person.ACCIDENT_NO + Person.VEHICLE_ID
                ↓
    Vehicle.ACCIDENT_NO + Vehicle.VEHICLE_ID

Rules:
- VEHICLE_ID must never be matched by itself;
- blank VEHICLE_ID values are handled separately in C06-04;
- unmatched non-empty references are relationship exceptions;
- do not create an artificial Vehicle;
- retain Person Raw lineage for diagnostics.
*/

WITH person_raw AS (
    SELECT
        raw_record_id,
        row_locator,
        payload ->> 'ACCIDENT_NO' AS accident_no,
        payload ->> 'PERSON_ID' AS person_id,
        payload ->> 'VEHICLE_ID' AS vehicle_id,
        payload ->> 'ROAD_USER_TYPE' AS road_user_type
    FROM raw.record
    WHERE source_id = 'official_vic'
      AND resource_id = 'official_vic_person'
      AND file_sha256 =
          '71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9'
      AND parser_version = 'csv-native-v1'
),

vehicle_raw AS (
    SELECT
        raw_record_id AS vehicle_raw_record_id,
        row_locator AS vehicle_row_locator,
        payload ->> 'ACCIDENT_NO' AS accident_no,
        payload ->> 'VEHICLE_ID' AS vehicle_id
    FROM raw.record
    WHERE source_id = 'official_vic'
      AND resource_id = 'official_vic_vehicle'
      AND file_sha256 =
          '05a7a1b9171abaeb5c188df549dee38edde6e76d5a03553988305a8280dccd12'
      AND parser_version = 'csv-native-v1'
),

nonblank_person_vehicle_refs AS (
    SELECT
        *
    FROM person_raw
    WHERE vehicle_id IS NOT NULL
      AND btrim(vehicle_id) <> ''
),

person_vehicle_check AS (
    SELECT
        p.raw_record_id,
        p.row_locator,
        p.accident_no,
        p.person_id,
        p.vehicle_id,
        p.road_user_type,
        v.vehicle_raw_record_id,
        v.vehicle_row_locator
    FROM nonblank_person_vehicle_refs p
    LEFT JOIN vehicle_raw v
        ON p.accident_no = v.accident_no
       AND p.vehicle_id = v.vehicle_id
)

SELECT
    'unmatched_nonblank_vehicle_ref' AS diagnostic_code,
    raw_record_id,
    row_locator,
    accident_no,
    person_id,
    vehicle_id,
    road_user_type
FROM person_vehicle_check
WHERE vehicle_raw_record_id IS NULL
ORDER BY
    accident_no,
    person_id;


/*
C06-04 — Blank Person VEHICLE_ID classification

Blank VEHICLE_ID must be treated separately from a non-empty orphan.

Current evidence:
- role 1 pedestrian + blank VEHICLE_ID:
  plausible candidate non-association, but not yet officially confirmed;
- role 9 unknown + blank VEHICLE_ID:
  unresolved;
- other roles + blank VEHICLE_ID:
  unexpected under the reviewed snapshot.

No Vehicle row is invented.
*/

WITH person_raw AS (
    SELECT
        raw_record_id,
        row_locator,
        payload ->> 'ACCIDENT_NO' AS accident_no,
        payload ->> 'PERSON_ID' AS person_id,
        payload ->> 'VEHICLE_ID' AS vehicle_id,
        payload ->> 'ROAD_USER_TYPE' AS road_user_type
    FROM raw.record
    WHERE source_id = 'official_vic'
      AND resource_id = 'official_vic_person'
      AND file_sha256 =
          '71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9'
      AND parser_version = 'csv-native-v1'
),

blank_vehicle_refs AS (
    SELECT
        raw_record_id,
        row_locator,
        accident_no,
        person_id,
        vehicle_id,
        road_user_type,
        CASE
            WHEN road_user_type = '1'
                THEN 'candidate_blank_vehicle_ref_pedestrian'

            WHEN road_user_type = '9'
                THEN 'unresolved_blank_vehicle_ref_unknown_role'

            ELSE 'unexpected_blank_vehicle_ref_other_role'
        END AS diagnostic_code
    FROM person_raw
    WHERE vehicle_id IS NULL
       OR btrim(vehicle_id) = ''
)

SELECT
    diagnostic_code,
    raw_record_id,
    row_locator,
    accident_no,
    person_id,
    vehicle_id,
    road_user_type
FROM blank_vehicle_refs
ORDER BY
    diagnostic_code,
    accident_no,
    person_id;


/*
C06-05 — Declared Person count reconciliation

Compare:

    Accident.NO_PERSONS
            vs
    number of Person rows for the same ACCIDENT_NO

Rules:
- compare against the full Person resource first;
- do not invent missing Person rows;
- do not introduce an automatic tolerance;
- keep both Accident and Person Raw locators for diagnostics;
- analytical scope is derived from the parent Accident occurrence date.
*/

WITH accident_raw AS (
    SELECT
        raw_record_id AS accident_raw_record_id,
        row_locator AS accident_row_locator,
        payload ->> 'ACCIDENT_NO' AS accident_no,
        (payload ->> 'ACCIDENT_DATE')::date AS accident_date,
        NULLIF(
            btrim(payload ->> 'NO_PERSONS'),
            ''
        )::integer AS declared_person_count
    FROM raw.record
    WHERE source_id = 'official_vic'
      AND resource_id = 'official_vic_accident'
      AND file_sha256 =
          'a148c00601fab10d44368df80492c594123700a7f9e334ff896fd215295e91d9'
      AND parser_version = 'csv-native-v1'
),

person_raw AS (
    SELECT
        raw_record_id,
        row_locator,
        payload ->> 'ACCIDENT_NO' AS accident_no,
        payload ->> 'PERSON_ID' AS person_id
    FROM raw.record
    WHERE source_id = 'official_vic'
      AND resource_id = 'official_vic_person'
      AND file_sha256 =
          '71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9'
      AND parser_version = 'csv-native-v1'
),

person_counts AS (
    SELECT
        accident_no,
        COUNT(*) AS actual_person_count,
        ARRAY_AGG(raw_record_id ORDER BY row_locator) AS person_raw_record_ids,
        ARRAY_AGG(row_locator ORDER BY row_locator) AS person_row_locators
    FROM person_raw
    GROUP BY accident_no
),

person_count_check AS (
    SELECT
        a.accident_raw_record_id,
        a.accident_row_locator,
        a.accident_no,
        a.accident_date,
        a.declared_person_count,
        COALESCE(p.actual_person_count, 0) AS actual_person_count,
        COALESCE(p.actual_person_count, 0) - a.declared_person_count
            AS person_count_delta,
        p.person_raw_record_ids,
        p.person_row_locators,
        (
            a.accident_date >= DATE '2020-01-01'
            AND a.accident_date < DATE '2025-01-01'
        ) AS in_2020_2024_scope
    FROM accident_raw a
    LEFT JOIN person_counts p
        ON a.accident_no = p.accident_no
)

SELECT
    'person_count_mismatch' AS diagnostic_code,
    accident_raw_record_id,
    accident_row_locator,
    accident_no,
    accident_date,
    declared_person_count,
    actual_person_count,
    person_count_delta,
    in_2020_2024_scope,
    person_raw_record_ids,
    person_row_locators
FROM person_count_check
WHERE declared_person_count IS DISTINCT FROM actual_person_count
ORDER BY
    accident_date,
    accident_no;
