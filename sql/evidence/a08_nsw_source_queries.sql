-- A08 NSW source-model and query evidence.
--
-- Run these statements on the same caller-owned transaction that temporarily
-- loaded the prepared official NSW Crash and Traffic Unit records.  Every view
-- is bound to the selected resource, file SHA-256 and parser version so another
-- release cannot silently enter the evidence.

-- Materialise native key fields once.  The indexes and ANALYZE statements
-- below prevent the parent check from repeatedly extracting JSON values and
-- performing an unbounded nested-loop scan.
-- name: setup_crash
CREATE TEMP TABLE a08_nsw_crash ON COMMIT DROP AS
SELECT
    r.raw_record_id,
    r.row_locator,
    r.payload,
    r.payload ->> 'Crash ID' AS crash_id,
    r.payload ->> 'Reporting year' AS reporting_year,
    r.payload ->> 'Year of crash' AS occurrence_year,
    r.payload ->> 'Month of crash' AS occurrence_month,
    r.payload ->> 'No. of traffic units involved' AS declared_unit_count
FROM raw.record AS r
WHERE r.source_id = 'official_nsw'
  AND r.resource_id = 'official_nsw_crash'
  AND r.file_sha256 = '7345189f017d9c842429674ecf2196cee728de46c0572ce2a85220f9bef49aa9'
  AND r.parser_version = 'xlsx-native-v1';

-- name: setup_crash_key_index
CREATE INDEX a08_nsw_crash_key_idx ON a08_nsw_crash (crash_id);

-- name: setup_crash_analyze
ANALYZE a08_nsw_crash;

-- name: setup_unit
CREATE TEMP TABLE a08_nsw_unit ON COMMIT DROP AS
SELECT
    r.raw_record_id,
    r.row_locator,
    r.payload,
    r.payload ->> 'Crash ID' AS crash_id,
    r.payload ->> 'Traffic unit ID' AS traffic_unit_id,
    r.payload ->> 'TU type group' AS unit_type_group
FROM raw.record AS r
WHERE r.source_id = 'official_nsw'
  AND r.resource_id = 'official_nsw_traffic_unit'
  AND r.file_sha256 = '95349666f63952c580edb08973a8ac80be39db98ba289ec8533d61feb6d55f1b'
  AND r.parser_version = 'xlsx-native-v1';

-- name: setup_unit_parent_index
CREATE INDEX a08_nsw_unit_parent_idx ON a08_nsw_unit (crash_id);

-- name: setup_unit_key_index
CREATE INDEX a08_nsw_unit_key_idx
ON a08_nsw_unit (crash_id, traffic_unit_id);

-- name: setup_unit_analyze
ANALYZE a08_nsw_unit;

-- name: source_counts
SELECT
    resource_name,
    actual_rows,
    expected_rows,
    actual_rows - expected_rows AS row_delta
FROM (
    SELECT
        'Crash'::text AS resource_name,
        (SELECT count(*) FROM a08_nsw_crash) AS actual_rows,
        92189::bigint AS expected_rows
    UNION ALL
    SELECT
        'Traffic Unit'::text,
        (SELECT count(*) FROM a08_nsw_unit),
        170962::bigint
) AS counts
ORDER BY resource_name;

-- name: key_and_parent_quality
WITH crash_duplicate_groups AS (
    SELECT crash_id
    FROM a08_nsw_crash
    WHERE NULLIF(btrim(crash_id), '') IS NOT NULL
    GROUP BY crash_id
    HAVING count(*) > 1
),
unit_duplicate_groups AS (
    SELECT crash_id, traffic_unit_id
    FROM a08_nsw_unit
    WHERE NULLIF(btrim(crash_id), '') IS NOT NULL
      AND NULLIF(btrim(traffic_unit_id), '') IS NOT NULL
    GROUP BY crash_id, traffic_unit_id
    HAVING count(*) > 1
)
SELECT
    (SELECT count(*) FROM a08_nsw_crash
     WHERE NULLIF(btrim(crash_id), '') IS NULL) AS blank_crash_keys,
    (SELECT count(*) FROM crash_duplicate_groups) AS duplicate_crash_key_groups,
    (SELECT count(*) FROM a08_nsw_unit
     WHERE NULLIF(btrim(crash_id), '') IS NULL
        OR NULLIF(btrim(traffic_unit_id), '') IS NULL) AS blank_unit_keys,
    (SELECT count(*) FROM unit_duplicate_groups) AS duplicate_unit_key_groups,
    (SELECT count(*)
     FROM a08_nsw_unit AS u
     LEFT JOIN a08_nsw_crash AS c ON c.crash_id = u.crash_id
     WHERE c.crash_id IS NULL) AS orphan_unit_rows;

-- name: occurrence_and_reporting_year_counts
SELECT year_kind, year_value, row_count
FROM (
    SELECT
        'occurrence_year'::text AS year_kind,
        occurrence_year AS year_value,
        count(*) AS row_count
    FROM a08_nsw_crash
    GROUP BY occurrence_year
    UNION ALL
    SELECT
        'reporting_year'::text,
        reporting_year,
        count(*)
    FROM a08_nsw_crash
    GROUP BY reporting_year
) AS year_counts
ORDER BY year_kind, year_value NULLS FIRST;

-- name: reporting_occurrence_year_differences
SELECT
    count(*) AS compared_crash_rows,
    count(*) FILTER (
        WHERE reporting_year IS DISTINCT FROM occurrence_year
    ) AS differing_year_rows
FROM a08_nsw_crash;

-- name: declared_unit_reconciliation
WITH observed AS (
    SELECT
        c.crash_id,
        c.declared_unit_count,
        count(u.traffic_unit_id) AS observed_unit_count
    FROM a08_nsw_crash AS c
    LEFT JOIN a08_nsw_unit AS u ON u.crash_id = c.crash_id
    GROUP BY c.crash_id, c.declared_unit_count
),
typed AS (
    SELECT
        crash_id,
        declared_unit_count,
        observed_unit_count,
        CASE
            WHEN declared_unit_count ~ '^[0-9]+$'
            THEN declared_unit_count::bigint
        END AS declared_unit_count_number
    FROM observed
)
SELECT
    count(*) AS crash_rows,
    count(*) FILTER (
        WHERE declared_unit_count_number IS NULL
    ) AS invalid_declared_counts,
    count(*) FILTER (
        WHERE declared_unit_count_number IS NOT NULL
          AND declared_unit_count_number <> observed_unit_count
    ) AS declared_unit_mismatches,
    sum(declared_unit_count_number) AS total_declared_units,
    sum(observed_unit_count) AS total_observed_units
FROM typed;

-- name: analysis_scope
WITH scoped_crashes AS (
    SELECT crash_id, occurrence_year, occurrence_month
    FROM a08_nsw_crash
    WHERE occurrence_year ~ '^[0-9]{4}$'
      AND occurrence_year::integer BETWEEN 2020 AND 2024
),
scoped_units AS (
    SELECT u.*
    FROM a08_nsw_unit AS u
    JOIN scoped_crashes AS c ON c.crash_id = u.crash_id
)
SELECT
    (SELECT count(*) FROM scoped_crashes) AS analysis_crash_rows,
    (SELECT count(*) FROM scoped_units) AS analysis_unit_rows,
    (SELECT count(*) FROM a08_nsw_crash
     WHERE occurrence_year = '2019') AS raw_only_2019_crash_rows,
    (SELECT count(*)
     FROM a08_nsw_unit AS u
     JOIN a08_nsw_crash AS c ON c.crash_id = u.crash_id
     WHERE c.occurrence_year = '2019') AS raw_only_2019_unit_rows,
    (SELECT count(DISTINCT (occurrence_year, occurrence_month))
     FROM scoped_crashes) AS covered_year_months;

-- name: relationship_examples
SELECT
    c.crash_id,
    rv.encode_business_key(c.crash_id) AS crash_business_key,
    u.traffic_unit_id,
    rv.encode_business_key(u.crash_id, u.traffic_unit_id) AS unit_business_key,
    u.unit_type_group
FROM a08_nsw_crash AS c
JOIN a08_nsw_unit AS u ON u.crash_id = c.crash_id
ORDER BY c.crash_id, u.traffic_unit_id
LIMIT 10;
