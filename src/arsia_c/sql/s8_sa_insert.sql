WITH typed AS (
 SELECT *, (payload->>'YEAR')::integer AS year, (payload->>'MONTH')::integer AS month,
  %(severity_map)s::jsonb->(payload->>'SEVERITY') AS classification,
  NULLIF(payload->>'FATALITIES','')::integer AS killed,
  NULLIF(payload->>'CASUALTIES','')::integer AS casualties,
  CASE WHEN pg_input_is_valid(payload->>'LATITUDE','numeric') THEN (payload->>'LATITUDE')::numeric END AS lat,
  CASE WHEN pg_input_is_valid(payload->>'LONGITUDE','numeric') THEN (payload->>'LONGITUDE')::numeric END AS lon
 FROM pg_temp.s8_crash
), located AS (
 SELECT *, COALESCE(%(map_enabled)s AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180, false) AS mappable
 FROM typed WHERE year BETWEEN %(year_from)s AND %(year_to)s
)
INSERT INTO pg_temp.arsia_i_crash
SELECT %(batch_id)s::uuid, %(source_id)s, %(release_scope)s,
 rv.encode_business_key(payload->>'CRASH_ID'), raw_record_id, year, month, NULL::date, 'month',
 payload->>'SEVERITY', COALESCE(classification->>'code','__MISSING__'), %(severity_version)s,
 (classification->>'fatal')::boolean, killed, casualties,
 classification IS NOT NULL, killed IS NOT NULL, casualties IS NOT NULL,
 CASE WHEN mappable THEN lat::numeric(10,7) END, CASE WHEN mappable THEN lon::numeric(10,7) END,
 CASE WHEN mappable THEN 'EPSG:4326' END, mappable, CASE WHEN mappable THEN raw_record_id END,
 COALESCE((SELECT jsonb_build_object('fields',jsonb_agg(jsonb_build_object(
   'field',field,'reason_code','missing','raw_token',token,'contract_version',%(contract_version)s::text)))
   FROM (VALUES ('fatal_crash_eligible',payload->>'SEVERITY',classification IS NULL),
                ('fatality_count',payload->>'FATALITIES',killed IS NULL),
                ('casualty_count',payload->>'CASUALTIES',casualties IS NULL)) r(field,token,missing)
   WHERE missing HAVING count(*)>0),'{}'::jsonb)
 || CASE WHEN mappable THEN '{}'::jsonb ELSE jsonb_build_object('location',jsonb_build_object(
   'reason_code',CASE WHEN NOT %(map_enabled)s THEN 'crs_unconfirmed'
     WHEN NULLIF(payload->>'LATITUDE','') IS NULL OR NULLIF(payload->>'LONGITUDE','') IS NULL
     THEN 'missing' ELSE 'invalid_coordinate' END,
   'candidate_raw_record_ids',jsonb_build_array(raw_record_id),
   'resolution','Crash retained without a trusted location.',
   'evidence_ref',%(location_evidence)s::text)) END
FROM located;
