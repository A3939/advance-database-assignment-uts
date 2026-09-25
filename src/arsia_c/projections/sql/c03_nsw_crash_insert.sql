-- C03 full typed projection. Raw text remains unchanged in raw.record.
WITH native AS (
 SELECT r.*,
        CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'Degree of crash - detailed', '') ELSE r.payload ->> 'Degree of crash - detailed' END AS severity,
        CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'Month of crash', '') ELSE r.payload ->> 'Month of crash' END AS month,
        (CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'No. killed', '') ELSE r.payload ->> 'No. killed' END)::integer AS killed,
        (CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'No. seriously injured', '') ELSE r.payload ->> 'No. seriously injured' END)::integer AS serious,
        (CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'No. moderately injured', '') ELSE r.payload ->> 'No. moderately injured' END)::integer AS moderate,
        (CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'No. minor-other injured', '') ELSE r.payload ->> 'No. minor-other injured' END)::integer AS minor,
        CASE WHEN pg_input_is_valid(r.payload ->> 'Latitude', 'numeric')
             THEN (r.payload ->> 'Latitude')::numeric END AS lat,
        CASE WHEN pg_input_is_valid(r.payload ->> 'Longitude', 'numeric')
             THEN (r.payload ->> 'Longitude')::numeric END AS lon
 FROM raw.record r WHERE r.source_id = %(source_id)s AND r.resource_id = %(crash_resource_id)s AND r.file_sha256 = %(crash_file_sha256)s AND r.parser_version = %(crash_parser_version)s AND (r.payload ->> 'Year of crash')::integer BETWEEN %(year_from)s AND %(year_to)s
), mapped AS (
 SELECT *, %(severity_map)s::jsonb -> severity AS classification,
        COALESCE(%(map_enabled)s AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180, false) AS usable_location,
        CASE WHEN NOT %(map_enabled)s THEN 'crs_unconfirmed'
             WHEN payload ->> 'Latitude' IS NULL OR payload ->> 'Latitude' = ''
               OR payload ->> 'Longitude' IS NULL OR payload ->> 'Longitude' = '' THEN 'missing'
             ELSE 'invalid_coordinate' END AS location_reason
 FROM native
)
INSERT INTO pg_temp.arsia_i_crash (
 batch_id,source_id,release_scope,crash_key,raw_record_id,
 occurrence_year,occurrence_month,occurrence_date,date_precision,
 severity_raw,severity_code,severity_definition_version,is_fatal_crash,
 fatality_count,casualty_count,fatal_crash_eligible,fatality_eligible,casualty_eligible,
 latitude,longitude,location_crs,map_eligible,location_record_id,quality_notes
)
SELECT %(batch_id)s::uuid, source_id, %(release_scope)s,
 rv.encode_business_key(payload ->> 'Crash ID'), raw_record_id,
 (payload ->> 'Year of crash')::integer,
 CASE btrim(month)
   WHEN 'January' THEN 1 WHEN 'February' THEN 2 WHEN 'March' THEN 3 WHEN 'April' THEN 4
   WHEN 'May' THEN 5 WHEN 'June' THEN 6 WHEN 'July' THEN 7 WHEN 'August' THEN 8
   WHEN 'September' THEN 9 WHEN 'October' THEN 10 WHEN 'November' THEN 11 WHEN 'December' THEN 12 END,
 NULL::date, CASE WHEN month IS NULL THEN 'year' ELSE 'month' END,
 payload ->> 'Degree of crash - detailed', COALESCE(classification ->> 'code', '__MISSING__'),
 %(severity_version)s, (classification ->> 'fatal')::boolean,
 killed, CASE WHEN killed IS NOT NULL AND serious IS NOT NULL AND moderate IS NOT NULL AND minor IS NOT NULL
              THEN (killed::bigint + serious + moderate + minor)::integer END,
 classification IS NOT NULL, killed IS NOT NULL,
 killed IS NOT NULL AND serious IS NOT NULL AND moderate IS NOT NULL AND minor IS NOT NULL,
 CASE WHEN usable_location THEN lat::numeric(10,7) END,
 CASE WHEN usable_location THEN lon::numeric(10,7) END,
 CASE WHEN usable_location THEN 'EPSG:4326' END, usable_location,
 CASE WHEN usable_location THEN raw_record_id END,
 COALESCE((SELECT jsonb_build_object('fields', jsonb_agg(jsonb_build_object(
     'field', field, 'reason_code', 'missing', 'raw_token', raw_token,
     'contract_version', %(crash_contract_version)s::text)))
   FROM (VALUES
     ('fatal_crash_eligible', payload ->> 'Degree of crash - detailed', classification IS NULL),
     ('fatality_count', payload ->> 'No. killed', killed IS NULL),
     ('casualty_count', NULL::text, killed IS NULL OR serious IS NULL OR moderate IS NULL OR minor IS NULL)
   ) AS reasons(field,raw_token,missing) WHERE missing HAVING count(*) > 0), '{}'::jsonb)
 || CASE WHEN usable_location THEN '{}'::jsonb ELSE jsonb_build_object('location', jsonb_build_object(
      'reason_code', location_reason, 'candidate_raw_record_ids', jsonb_build_array(raw_record_id),
      'resolution', 'Coordinates, CRS and location lineage cleared; crash retained.',
      'evidence_ref', %(location_evidence)s::text)) END
FROM mapped;
