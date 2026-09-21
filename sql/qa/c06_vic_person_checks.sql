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
