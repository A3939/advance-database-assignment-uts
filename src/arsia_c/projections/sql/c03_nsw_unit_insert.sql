-- Map only declared native types; missing types retain the real unit.
WITH native AS (
 SELECT u.*, CASE WHEN %(empty_is_missing)s THEN NULLIF(u.payload ->> 'TU type group', '')
                 ELSE u.payload ->> 'TU type group' END AS native_type
 FROM raw.record u JOIN raw.record c ON c.payload ->> 'Crash ID' = u.payload ->> 'Crash ID'
 WHERE c.source_id = %(source_id)s AND c.resource_id = %(crash_resource_id)s
   AND c.file_sha256 = %(crash_file_sha256)s AND c.parser_version = %(crash_parser_version)s
   AND u.source_id = %(source_id)s AND u.resource_id = %(unit_resource_id)s
   AND u.file_sha256 = %(unit_file_sha256)s AND u.parser_version = %(unit_parser_version)s
   AND (c.payload ->> 'Year of crash')::integer BETWEEN %(year_from)s AND %(year_to)s
)
INSERT INTO pg_temp.arsia_i_unit (
 batch_id,source_id,release_scope,unit_key,crash_key,raw_record_id,
 unit_type_raw,unit_type_code,statistical_scope,count_eligible,quality_notes
)
SELECT %(batch_id)s::uuid, source_id, %(release_scope)s,
 rv.encode_business_key(payload ->> 'Crash ID', payload ->> 'Traffic unit ID'),
 rv.encode_business_key(payload ->> 'Crash ID'), raw_record_id,
 payload ->> 'TU type group', %(unit_types)s::jsonb ->> native_type,
 %(statistical_scope)s, native_type IS NOT NULL,
 CASE WHEN native_type IS NOT NULL THEN '{}'::jsonb ELSE jsonb_build_object('fields', jsonb_build_array(
   jsonb_build_object('field', 'unit_type_code', 'reason_code', 'missing',
                     'raw_token', payload ->> 'TU type group', 'contract_version', %(unit_contract_version)s::text))) END
FROM native;
