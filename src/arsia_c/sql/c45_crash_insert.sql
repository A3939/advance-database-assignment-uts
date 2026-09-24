WITH mapped AS (
 SELECT *, %(severity_map)s::jsonb->severity AS classification,
  COALESCE(%(state)s='QLD' AND %(map_enabled)s AND lat BETWEEN -90 AND 90 AND lon BETWEEN -180 AND 180,false) AS located
 FROM pg_temp.c45_values WHERE year BETWEEN %(year_from)s AND %(year_to)s
)
INSERT INTO pg_temp.arsia_i_crash
SELECT %(batch_id)s::uuid,%(source_id)s,%(release_scope)s,crash_key,raw_record_id,
 year,month,day,precision,severity,COALESCE(classification->>'code','__MISSING__'),%(severity_version)s,
 (classification->>'fatal')::boolean,killed,casualties,classification IS NOT NULL,killed IS NOT NULL,casualties IS NOT NULL,
 CASE WHEN located THEN lat::numeric(10,7) END, CASE WHEN located THEN lon::numeric(10,7) END,
 CASE WHEN located THEN 'EPSG:4326' END,located,CASE WHEN located THEN raw_record_id END,
 COALESCE((SELECT jsonb_build_object('fields',jsonb_agg(jsonb_build_object('field',field,'reason_code','missing',
  'raw_token',token,'contract_version',%(contract_version)s::text))) FROM (VALUES
  ('fatal_crash_eligible',severity,classification IS NULL),
  ('fatality_count',payload->>%(fatality_field)s,killed IS NULL),
  ('casualty_count',NULL::text,casualties IS NULL)) r(field,token,missing) WHERE missing HAVING count(*)>0),'{}'::jsonb)
 || CASE WHEN located THEN '{}'::jsonb ELSE jsonb_build_object('location',jsonb_build_object(
  'reason_code',CASE WHEN %(state)s='VIC' THEN 'no_location' WHEN NOT %(map_enabled)s THEN 'definition_unconfirmed'
                    WHEN NULLIF(payload->>'Crash_Latitude','') IS NULL OR NULLIF(payload->>'Crash_Longitude','') IS NULL THEN 'missing' ELSE 'invalid_coordinate' END,
  'candidate_raw_record_ids',CASE WHEN %(state)s='VIC' THEN '[]'::jsonb ELSE jsonb_build_array(raw_record_id) END,
  'resolution',CASE WHEN %(state)s='VIC' THEN 'Pending C07 assembly in the same projection callback.'
                    WHEN NOT %(map_enabled)s THEN CASE WHEN %(dataset_kind)s='official'
                      THEN 'Known GDA2020 source datum; EPSG:4326 operation unverified. Official map disabled.'
                      ELSE 'Synthetic source CRS is unconfirmed; map disabled.' END
                    ELSE 'Untrusted source coordinate; crash retained without location.' END,
  'evidence_ref',%(location_evidence)s::text)) END
FROM mapped;
