-- One JSON parameter supplies selected files, years and confirmed source rules.
-- Read the complete selected parents before assigning an analysis year.
WITH
parameters AS (
    SELECT %s::jsonb AS value
),
settings AS (
    SELECT
        (value #>> '{analysis,year_from}')::integer AS year_from,
        (value #>> '{analysis,year_to}')::integer AS year_to,
        (value ->> 'blank_vehicle_allowed')::boolean AS blank_vehicle_allowed,
        (value ->> 'count_scope_confirmed')::boolean AS count_scope_confirmed,
        COALESCE((value ->> 'restricted_diagnostics')::boolean, false) AS restricted_diagnostics,
        U&'^[\0009-\000D\0020\0085\00A0\1680\2000-\200A\2028\2029\202F\205F\3000]*$'
            AS whitespace_pattern
    FROM parameters
),
files AS (
    SELECT f.*
    FROM parameters p
    CROSS JOIN LATERAL jsonb_to_recordset(p.value -> 'files') AS f(
        role text, source_id text, resource_id text, file_sha256 text,
        parser_version text, raw_count bigint
    )
),
selected_raw AS MATERIALIZED (
    SELECT f.role, r.*
    FROM files f
    JOIN raw.record r
      ON r.source_id = f.source_id
     AND r.resource_id = f.resource_id
     AND r.file_sha256 = f.file_sha256
     AND r.parser_version = f.parser_version
),
native AS (
    SELECT
        r.*,
        r.payload ->> 'ACCIDENT_NO' AS accident_no,
        r.payload ->> 'PERSON_ID' AS person_id,
        r.payload ->> 'VEHICLE_ID' AS vehicle_id,
        r.payload ->> 'ACCIDENT_DATE' AS date_text,
        r.payload ->> 'NO_PERSONS' AS count_text,
        COALESCE(jsonb_typeof(r.payload -> 'ACCIDENT_NO') = 'string'
            AND NOT (r.payload ->> 'ACCIDENT_NO') ~ s.whitespace_pattern, false)
            AS accident_key_valid,
        COALESCE(jsonb_typeof(r.payload -> 'PERSON_ID') = 'string'
            AND NOT (r.payload ->> 'PERSON_ID') ~ s.whitespace_pattern, false)
            AS person_key_valid,
        COALESCE(jsonb_typeof(r.payload -> 'VEHICLE_ID') = 'string'
            AND NOT (r.payload ->> 'VEHICLE_ID') ~ s.whitespace_pattern, false)
            AS vehicle_key_valid,
        r.payload ->> 'VEHICLE_ID' IS NULL
            OR r.payload -> 'VEHICLE_ID' = '""'::jsonb AS vehicle_missing
    FROM selected_raw r
    CROSS JOIN settings s
),
accident_values AS (
    SELECT
        n.*,
        -- CASE keeps invalid native values away from casts.
        CASE WHEN jsonb_typeof(payload -> 'ACCIDENT_DATE') = 'string'
                   AND date_text ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                   AND pg_input_is_valid(date_text, 'date')
             THEN date_text::date END AS accident_date,
        CASE WHEN jsonb_typeof(payload -> 'NO_PERSONS') = 'string'
                   AND count_text ~ '^[0-9]+$'
                   AND pg_input_is_valid(count_text, 'integer')
             THEN count_text::integer END AS declared_count,
        count_text IS NULL OR payload -> 'NO_PERSONS' = '""'::jsonb
            AS count_missing
    FROM native n
    WHERE role = 'accident'
),
accident_groups AS (
    SELECT
        source_id, accident_no, count(*) AS parent_match_count,
        min(accident_date) AS accident_date,
        min(row_locator) AS parent_locator
    FROM accident_values
    WHERE accident_key_valid
    GROUP BY source_id, accident_no
),
person_values AS (
    SELECT n.*,
        count(*) FILTER (WHERE accident_key_valid AND person_key_valid)
            OVER (PARTITION BY source_id, accident_no, person_id) AS key_count
    FROM native n
    WHERE role = 'person'
),
person_counts AS (
    SELECT source_id, accident_no, count(*) AS observed_count
    FROM person_values
    WHERE accident_key_valid
    GROUP BY source_id, accident_no
),
vehicle_values AS (
    SELECT n.*,
        count(*) FILTER (WHERE accident_key_valid AND vehicle_key_valid)
            OVER (PARTITION BY source_id, accident_no, vehicle_id) AS key_count
    FROM native n
    WHERE role = 'vehicle'
),
vehicle_groups AS (
    SELECT source_id, accident_no, vehicle_id, count(*) AS vehicle_match_count
    FROM vehicle_values
    WHERE accident_key_valid AND vehicle_key_valid
    GROUP BY source_id, accident_no, vehicle_id
),
accident_checks AS (
    SELECT
        a.*, g.parent_match_count,
        CASE WHEN a.accident_key_valid THEN COALESCE(p.observed_count, 0) END
            AS observed_count,
        CASE
            WHEN NOT a.accident_key_valid OR g.parent_match_count <> 1 THEN 'invalid'
            WHEN a.count_missing THEN 'missing'
            WHEN a.declared_count IS NULL THEN 'invalid'
            WHEN s.restricted_diagnostics THEN 'diagnostic'
            WHEN NOT s.count_scope_confirmed THEN 'unconfirmed'
            ELSE 'compared'
        END AS count_state,
        CASE WHEN a.accident_key_valid AND g.parent_match_count = 1
                   AND a.declared_count IS NOT NULL AND s.count_scope_confirmed
             THEN COALESCE(p.observed_count, 0) - a.declared_count END AS count_delta,
        CASE WHEN a.accident_key_valid AND g.parent_match_count = 1
                   AND a.declared_count IS NOT NULL
             THEN COALESCE(p.observed_count, 0) - a.declared_count END
            AS diagnostic_count_delta,
        extract(year FROM a.accident_date) BETWEEN s.year_from AND s.year_to
            AS in_scope
    FROM accident_values a
    CROSS JOIN settings s
    LEFT JOIN accident_groups g
      ON a.accident_key_valid AND g.source_id = a.source_id
     AND g.accident_no = a.accident_no
    LEFT JOIN person_counts p
      ON a.accident_key_valid AND p.source_id = a.source_id
     AND p.accident_no = a.accident_no
),
mismatch_references AS (
    -- Aggregate only mismatches; joining grouped parents cannot multiply counts.
    SELECT p.source_id, p.accident_no,
        jsonb_agg(jsonb_build_object(
            'raw_record_id', p.raw_record_id::text,
            'resource_id', p.resource_id,
            'row_locator', p.row_locator
        ) ORDER BY p.resource_id, p.file_sha256, p.parser_version,
            CASE WHEN p.row_locator ~ '^csv:[0-9]+$'
                 THEN substring(p.row_locator FROM 5)::numeric END,
            p.row_locator, p.raw_record_id) AS person_references
    FROM person_values p
    JOIN accident_checks a
      ON a.source_id = p.source_id AND a.accident_no = p.accident_no
     AND (a.count_delta <> 0 OR a.diagnostic_count_delta <> 0)
    GROUP BY p.source_id, p.accident_no
),
person_checks AS (
    SELECT
        p.*, a.accident_date, a.parent_locator,
        COALESCE(a.parent_match_count, 0) AS parent_match_count,
        COALESCE(v.vehicle_match_count, 0) AS vehicle_match_count,
        CASE WHEN a.parent_match_count = 1
             THEN extract(year FROM a.accident_date) BETWEEN s.year_from AND s.year_to
             END AS in_scope,
        CASE
            WHEN p.vehicle_missing THEN CASE
                WHEN s.restricted_diagnostics THEN CASE
                    WHEN p.payload -> 'VEHICLE_ID' = '""'::jsonb
                     AND p.payload -> 'ROAD_USER_TYPE' = '"1"'::jsonb
                     AND p.payload -> 'SEATING_POSITION' = '"NA"'::jsonb
                    THEN 'allowed_pedestrian_blank' ELSE 'unresolved_blank' END
                WHEN s.blank_vehicle_allowed THEN 'allowed_blank'
                WHEN s.blank_vehicle_allowed IS NULL THEN 'unresolved_blank'
                ELSE 'forbidden_blank' END
            WHEN NOT p.vehicle_key_valid THEN 'invalid_whitespace_or_type'
            WHEN NOT p.accident_key_valid THEN 'invalid_accident_key'
            WHEN COALESCE(v.vehicle_match_count, 0) = 0 THEN 'unmatched'
            WHEN v.vehicle_match_count > 1 THEN 'ambiguous'
            ELSE 'matched'
        END AS vehicle_reference
    FROM person_values p
    CROSS JOIN settings s
    LEFT JOIN accident_groups a
      ON p.accident_key_valid AND a.source_id = p.source_id
     AND a.accident_no = p.accident_no
    LEFT JOIN vehicle_groups v
      ON p.accident_key_valid AND p.vehicle_key_valid
     AND v.source_id = p.source_id
     AND v.accident_no = p.accident_no AND v.vehicle_id = p.vehicle_id
),
rows AS (
    SELECT jsonb_build_object(
        'kind', 'file', 'role', f.role,
        'source_id', f.source_id, 'resource_id', f.resource_id,
        'file_sha256', f.file_sha256, 'parser_version', f.parser_version,
        'expected_count', f.raw_count, 'actual_count', count(r.raw_record_id),
        'in_scope', NULL,
        'issues', CASE WHEN count(r.raw_record_id) = f.raw_count THEN '[]'::jsonb
                       ELSE '["selected_raw_count_mismatch"]'::jsonb END
    ) AS result
    FROM files f
    LEFT JOIN selected_raw r
      ON r.role = f.role AND r.source_id = f.source_id
     AND r.resource_id = f.resource_id AND r.file_sha256 = f.file_sha256
     AND r.parser_version = f.parser_version
    GROUP BY f.role, f.source_id, f.resource_id, f.file_sha256,
        f.parser_version, f.raw_count

    UNION ALL
    SELECT jsonb_build_object(
        'kind', 'accident',
        'source_id', a.source_id, 'resource_id', a.resource_id,
        'file_sha256', a.file_sha256, 'parser_version', a.parser_version,
        'row_locator', a.row_locator, 'raw_record_id', a.raw_record_id::text,
        'accident_no', a.payload -> 'ACCIDENT_NO',
        'date_text', a.payload -> 'ACCIDENT_DATE',
        'count_text', a.payload -> 'NO_PERSONS',
        'in_scope', a.in_scope, 'declared_count', a.declared_count,
        'observed_count', a.observed_count, 'count_delta', a.count_delta,
        'count_state', a.count_state,
        'diagnostic_count_delta', a.diagnostic_count_delta,
        'person_references', COALESCE(m.person_references, '[]'::jsonb),
        'vehicle_references', CASE WHEN a.diagnostic_count_delta <> 0 THEN
            COALESCE((SELECT jsonb_agg(jsonb_build_object(
                'resource_id', v.resource_id, 'row_locator', v.row_locator,
                'raw_record_id', v.raw_record_id::text) ORDER BY v.row_locator)
                FROM vehicle_values v WHERE v.source_id = a.source_id
                AND v.accident_no = a.accident_no), '[]'::jsonb) ELSE '[]'::jsonb END,
        'issues', to_jsonb(array_remove(ARRAY[
            CASE WHEN NOT a.accident_key_valid THEN 'invalid_accident_key' END,
            CASE WHEN a.parent_match_count > 1 THEN 'duplicate_accident_key' END,
            CASE WHEN a.accident_date IS NULL THEN 'invalid_accident_date' END,
            CASE WHEN NOT a.count_missing AND a.declared_count IS NULL
                 THEN 'invalid_person_count' END,
            CASE WHEN NOT s.count_scope_confirmed AND NOT s.restricted_diagnostics
                 THEN 'person_count_scope_unconfirmed' END,
            CASE WHEN a.count_delta <> 0 THEN 'person_count_mismatch' END
        ]::text[], NULL))
    )
    FROM accident_checks a
    CROSS JOIN settings s
    LEFT JOIN mismatch_references m
      ON m.source_id = a.source_id AND m.accident_no = a.accident_no

    UNION ALL
    SELECT jsonb_build_object(
        'kind', 'person',
        'source_id', p.source_id, 'resource_id', p.resource_id,
        'file_sha256', p.file_sha256, 'parser_version', p.parser_version,
        'row_locator', p.row_locator, 'raw_record_id', p.raw_record_id::text,
        'accident_no', p.payload -> 'ACCIDENT_NO',
        'person_id', p.payload -> 'PERSON_ID', 'vehicle_id', p.payload -> 'VEHICLE_ID',
        'road_user_type', p.payload -> 'ROAD_USER_TYPE',
        'native_person_fields', jsonb_build_object(
            'ACCIDENT_NO', p.payload -> 'ACCIDENT_NO', 'PERSON_ID', p.payload -> 'PERSON_ID',
            'VEHICLE_ID', p.payload -> 'VEHICLE_ID', 'ROAD_USER_TYPE', p.payload -> 'ROAD_USER_TYPE',
            'INJ_LEVEL', p.payload -> 'INJ_LEVEL', 'SEATING_POSITION', p.payload -> 'SEATING_POSITION'),
        'occurrence_date', to_char(p.accident_date, 'YYYY-MM-DD'),
        'parent_locator', p.parent_locator,
        'available_vehicle_refs', CASE WHEN p.vehicle_reference = 'unmatched' THEN
            COALESCE((SELECT jsonb_agg(jsonb_build_object(
                'resource_id', v.resource_id, 'row_locator', v.row_locator,
                'raw_record_id', v.raw_record_id::text) ORDER BY v.row_locator)
                FROM vehicle_values v WHERE v.source_id = p.source_id
                AND v.accident_no = p.accident_no), '[]'::jsonb) ELSE '[]'::jsonb END,
        'in_scope', p.in_scope, 'parent_match_count', p.parent_match_count,
        'vehicle_match_count', p.vehicle_match_count,
        'vehicle_reference', p.vehicle_reference,
        'issues', to_jsonb(array_remove(ARRAY[
            CASE WHEN NOT p.accident_key_valid THEN 'invalid_accident_key' END,
            CASE WHEN NOT p.person_key_valid THEN 'invalid_person_key' END,
            CASE WHEN p.accident_key_valid AND p.person_key_valid AND p.key_count > 1
                 THEN 'duplicate_person_key' END,
            CASE WHEN p.accident_key_valid AND p.parent_match_count = 0
                 THEN 'missing_accident_parent' END,
            CASE WHEN p.parent_match_count > 1 THEN 'ambiguous_accident_parent' END,
            CASE WHEN p.vehicle_reference = 'invalid_whitespace_or_type'
                 THEN 'invalid_vehicle_reference' END,
            CASE WHEN p.vehicle_reference = 'unmatched' THEN 'unmatched_nonblank_vehicle_ref' END,
            CASE WHEN p.vehicle_reference = 'ambiguous' THEN 'ambiguous_vehicle_reference' END,
            CASE WHEN p.vehicle_reference = 'unresolved_blank'
                 THEN 'blank_vehicle_reference_unconfirmed' END,
            CASE WHEN p.vehicle_reference = 'forbidden_blank'
                 THEN 'blank_vehicle_reference_forbidden' END
        ]::text[], NULL))
    )
    FROM person_checks p

    UNION ALL
    SELECT jsonb_build_object(
        'kind', 'vehicle',
        'source_id', v.source_id, 'resource_id', v.resource_id,
        'file_sha256', v.file_sha256, 'parser_version', v.parser_version,
        'row_locator', v.row_locator, 'raw_record_id', v.raw_record_id::text,
        'accident_no', v.payload -> 'ACCIDENT_NO',
        'vehicle_id', v.payload -> 'VEHICLE_ID',
        'in_scope', CASE WHEN a.parent_match_count = 1
            THEN extract(year FROM a.accident_date) BETWEEN s.year_from AND s.year_to END,
        'parent_match_count', COALESCE(a.parent_match_count, 0),
        'issues', to_jsonb(array_remove(ARRAY[
            CASE WHEN NOT v.accident_key_valid THEN 'invalid_accident_key' END,
            CASE WHEN NOT v.vehicle_key_valid THEN 'invalid_vehicle_key' END,
            CASE WHEN v.accident_key_valid AND v.vehicle_key_valid AND v.key_count > 1
                 THEN 'duplicate_vehicle_key' END,
            CASE WHEN v.accident_key_valid AND COALESCE(a.parent_match_count, 0) = 0
                 THEN 'missing_accident_parent' END,
            CASE WHEN a.parent_match_count > 1 THEN 'ambiguous_accident_parent' END
        ]::text[], NULL))
    )
    FROM vehicle_values v
    CROSS JOIN settings s
    LEFT JOIN accident_groups a
      ON v.accident_key_valid AND a.source_id = v.source_id
     AND a.accident_no = v.accident_no
)
SELECT result
FROM rows
ORDER BY result ->> 'kind', result ->> 'resource_id',
    result ->> 'file_sha256', result ->> 'parser_version',
    CASE WHEN result ->> 'row_locator' ~ '^csv:[0-9]+$'
         THEN substring(result ->> 'row_locator' FROM 5)::numeric END,
    result ->> 'row_locator', result ->> 'raw_record_id';
