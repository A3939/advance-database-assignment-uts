-- Key/parent checks already covered the complete snapshot.
WITH native AS (
 SELECT CASE WHEN %(empty_is_missing)s THEN NULLIF(u.payload ->> 'TU type group', '')
             ELSE u.payload ->> 'TU type group' END AS unit_type
 FROM raw.record u JOIN raw.record c ON c.payload ->> 'Crash ID' = u.payload ->> 'Crash ID'
 WHERE c.source_id = %(source_id)s AND c.resource_id = %(crash_resource_id)s
   AND c.file_sha256 = %(crash_file_sha256)s AND c.parser_version = %(crash_parser_version)s
   AND u.source_id = %(source_id)s AND u.resource_id = %(unit_resource_id)s
   AND u.file_sha256 = %(unit_file_sha256)s AND u.parser_version = %(unit_parser_version)s
   AND (c.payload ->> 'Year of crash')::integer BETWEEN %(year_from)s AND %(year_to)s
)
SELECT count(*) FROM native
WHERE unit_type IS NOT NULL AND NOT (%(unit_types)s::jsonb ? unit_type);
