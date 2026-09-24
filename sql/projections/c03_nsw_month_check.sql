-- Missingness follows the profile; never downgrade unknown month text.
WITH native AS (
 SELECT CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'Month of crash', '') ELSE r.payload ->> 'Month of crash' END AS month
 FROM raw.record r WHERE r.source_id = %(source_id)s AND r.resource_id = %(crash_resource_id)s AND r.file_sha256 = %(crash_file_sha256)s AND r.parser_version = %(crash_parser_version)s AND (r.payload ->> 'Year of crash')::integer BETWEEN %(year_from)s AND %(year_to)s
)
SELECT count(*) FROM native
WHERE month IS NOT NULL AND btrim(month) NOT IN (
 'January','February','March','April','May','June',
 'July','August','September','October','November','December'
);
