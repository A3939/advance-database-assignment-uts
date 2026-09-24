-- Validate the complete snapshot before casting or selecting analysis years.
SELECT count(*) FROM raw.record r
WHERE r.source_id = %(source_id)s AND r.resource_id = %(crash_resource_id)s AND r.file_sha256 = %(crash_file_sha256)s AND r.parser_version = %(crash_parser_version)s
AND CASE WHEN (r.payload ->> 'Year of crash') ~ '^[0-9]{1,4}$'
    THEN (r.payload ->> 'Year of crash')::integer NOT BETWEEN 1900 AND 2100
    ELSE true END;
