-- D10 QLD source-model evidence queries.
-- Scope: exact pinned official_qld crash file, occurrence years 2020-2024.
-- Run with SELECT on raw.record and published/canonical views plus TEMP privilege.
-- The temporary view is session-local, creates no Unit rows, and is removed by ROLLBACK.

BEGIN;

CREATE TEMPORARY VIEW d10_qld_native AS
SELECT
    r.raw_record_id,
    r.row_locator,
    r.payload,
    btrim(r.payload ->> 'Crash_Ref_Number') AS crash_ref_number,
    CASE WHEN btrim(r.payload ->> 'Crash_Year') ~ '^[0-9]{4}$'
         THEN (btrim(r.payload ->> 'Crash_Year'))::integer END AS crash_year,
    CASE btrim(r.payload ->> 'Crash_Month')
         WHEN 'January' THEN 1 WHEN 'February' THEN 2 WHEN 'March' THEN 3
         WHEN 'April' THEN 4 WHEN 'May' THEN 5 WHEN 'June' THEN 6
         WHEN 'July' THEN 7 WHEN 'August' THEN 8 WHEN 'September' THEN 9
         WHEN 'October' THEN 10 WHEN 'November' THEN 11 WHEN 'December' THEN 12
    END AS crash_month,
    btrim(r.payload ->> 'Crash_Severity') AS crash_severity
FROM raw.record AS r
WHERE r.source_id = 'official_qld'
  AND r.resource_id = 'official_qld_crash'
  AND r.file_sha256 = '975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704'
  AND r.parser_version = 'csv-native-v1';

-- Q1. Native grain and key: one source row per opaque text key.
SELECT
    count(*) AS full_source_rows,
    count(*) FILTER (WHERE crash_ref_number IS NULL OR crash_ref_number = '') AS blank_keys,
    count(DISTINCT crash_ref_number) AS distinct_nonblank_keys,
    count(*) - count(DISTINCT crash_ref_number) AS duplicate_or_blank_keys,
    count(*) FILTER (WHERE crash_year BETWEEN 2020 AND 2024) AS analysis_rows
FROM d10_qld_native;

-- Q2. Traceable key examples. Never derive the year from Crash_Ref_Number.
SELECT row_locator, crash_ref_number, crash_year, crash_month, crash_severity
FROM d10_qld_native
WHERE crash_year BETWEEN 2020 AND 2024
ORDER BY row_locator
LIMIT 5;

-- Q3. Actual month coverage. A missing month stays NULL and is not assigned.
SELECT crash_year, crash_month, count(*) AS crash_count
FROM d10_qld_native
WHERE crash_year BETWEEN 2020 AND 2024
GROUP BY crash_year, crash_month
ORDER BY crash_year, crash_month NULLS LAST;

-- Q4. Native severity categories, including an explicit zero PDO row and missing row.
WITH categories(native_value, display_order) AS (
    VALUES ('Fatal', 1), ('Hospitalisation', 2), ('Medical treatment', 3),
           ('Minor injury', 4), ('Property damage only', 5), ('__MISSING__', 6)
), counts AS (
    SELECT coalesce(nullif(crash_severity, ''), '__MISSING__') AS native_value,
           count(*) AS crash_count
    FROM d10_qld_native
    WHERE crash_year BETWEEN 2020 AND 2024
    GROUP BY coalesce(nullif(crash_severity, ''), '__MISSING__')
)
SELECT categories.native_value, coalesce(counts.crash_count, 0) AS crash_count
FROM categories LEFT JOIN counts USING (native_value)
ORDER BY categories.display_order;

-- Q5. Unknown/invalid casualty values and the source totals.
-- Cast only registered nonnegative integer tokens; do not turn missing values into zero.
WITH values AS (
    SELECT payload,
           ARRAY[
             payload ->> 'Count_Casualty_Fatality',
             payload ->> 'Count_Casualty_Hospitalised',
             payload ->> 'Count_Casualty_MedicallyTreated',
             payload ->> 'Count_Casualty_MinorInjury',
             payload ->> 'Count_Casualty_Total'
           ] AS raw_counts
    FROM d10_qld_native
    WHERE crash_year BETWEEN 2020 AND 2024
), checked AS (
    SELECT *,
           EXISTS (SELECT 1 FROM unnest(raw_counts) v WHERE v IS NULL OR btrim(v) = '') AS has_missing,
           EXISTS (SELECT 1 FROM unnest(raw_counts) v WHERE btrim(v) !~ '^[0-9]+$') AS has_invalid
    FROM values
)
SELECT
    count(*) FILTER (WHERE has_missing) AS rows_with_missing_count,
    count(*) FILTER (WHERE has_invalid) AS rows_with_invalid_count,
    count(*) FILTER (
      WHERE NOT has_invalid AND NOT has_missing
        AND (payload ->> 'Count_Casualty_Fatality')::bigint
          + (payload ->> 'Count_Casualty_Hospitalised')::bigint
          + (payload ->> 'Count_Casualty_MedicallyTreated')::bigint
          + (payload ->> 'Count_Casualty_MinorInjury')::bigint
          <> (payload ->> 'Count_Casualty_Total')::bigint
    ) AS component_mismatch_rows,
    sum((payload ->> 'Count_Casualty_Fatality')::bigint)
      FILTER (WHERE NOT has_invalid AND NOT has_missing) AS fatality_sum,
    sum((payload ->> 'Count_Casualty_Total')::bigint)
      FILTER (WHERE NOT has_invalid AND NOT has_missing) AS casualty_total_sum
FROM checked;

-- Q6. Count_Unit_* are aggregate attributes on each crash row.
-- Summing them is source profiling only; this query creates no Unit identity or relationship.
WITH values AS (
    SELECT category, raw_value
    FROM d10_qld_native
    CROSS JOIN LATERAL (VALUES
      ('Count_Unit_Car', payload ->> 'Count_Unit_Car'),
      ('Count_Unit_Motorcycle_Moped', payload ->> 'Count_Unit_Motorcycle_Moped'),
      ('Count_Unit_Truck', payload ->> 'Count_Unit_Truck'),
      ('Count_Unit_Bus', payload ->> 'Count_Unit_Bus'),
      ('Count_Unit_Bicycle', payload ->> 'Count_Unit_Bicycle'),
      ('Count_Unit_Pedestrian', payload ->> 'Count_Unit_Pedestrian'),
      ('Count_Unit_Other', payload ->> 'Count_Unit_Other')
    ) AS native(category, raw_value)
    WHERE crash_year BETWEEN 2020 AND 2024
)
SELECT category,
       count(*) FILTER (WHERE raw_value IS NULL OR btrim(raw_value) = '') AS missing_rows,
       count(*) FILTER (WHERE raw_value IS NOT NULL AND btrim(raw_value) !~ '^[0-9]+$') AS invalid_rows,
       sum(raw_value::bigint) FILTER (WHERE btrim(raw_value) ~ '^[0-9]+$') AS aggregate_sum,
       count(*) FILTER (WHERE btrim(raw_value) ~ '^[1-9][0-9]*$') AS crash_rows_with_nonzero_category
FROM values
GROUP BY category
ORDER BY category;

-- Q7. Native coordinate presence is not published map eligibility.
-- These are GDA2020 values; do not relabel them EPSG:4326.
SELECT
    count(*) AS analysis_rows,
    count(*) FILTER (
      WHERE nullif(btrim(payload ->> 'Crash_Latitude'), '') IS NOT NULL
        AND nullif(btrim(payload ->> 'Crash_Longitude'), '') IS NOT NULL
    ) AS native_coordinate_rows,
    count(*) FILTER (
      WHERE nullif(btrim(payload ->> 'Crash_Latitude'), '') IS NULL
         OR nullif(btrim(payload ->> 'Crash_Longitude'), '') IS NULL
    ) AS missing_coordinate_rows,
    'GDA2020'::text AS source_crs,
    false AS published_map_available,
    'definition_unconfirmed'::text AS reason_code
FROM d10_qld_native
WHERE crash_year BETWEEN 2020 AND 2024;

-- Q8. Published boundary from B's successful official batch.
-- Expected for official_qld: 66,624 crashes, zero eligible points, 66,624 unmapped;
-- canonical.unit has zero QLD rows because no unit-detail records exist.
SELECT
    count(*) AS crash_count,
    count(*) FILTER (WHERE map_eligible) AS published_map_count,
    count(*) FILTER (WHERE NOT map_eligible) AS published_unmapped_count,
    (SELECT count(*) FROM canonical.unit AS u
      WHERE u.batch_id = 'd6f0e958-7c94-4f2f-ba85-9d44e597cc02'::uuid
        AND u.source_id = 'official_qld') AS canonical_unit_count
FROM canonical.crash AS c
WHERE c.batch_id = 'd6f0e958-7c94-4f2f-ba85-9d44e597cc02'::uuid
  AND c.source_id = 'official_qld';

ROLLBACK;
