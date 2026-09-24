-- Validate in-scope values before any count cast or insert.
WITH native AS (
 SELECT CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'Degree of crash - detailed', '') ELSE r.payload ->> 'Degree of crash - detailed' END AS severity,
        ARRAY[CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'No. killed', '') ELSE r.payload ->> 'No. killed' END, CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'No. seriously injured', '') ELSE r.payload ->> 'No. seriously injured' END, CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'No. moderately injured', '') ELSE r.payload ->> 'No. moderately injured' END, CASE WHEN %(empty_is_missing)s THEN NULLIF(r.payload ->> 'No. minor-other injured', '') ELSE r.payload ->> 'No. minor-other injured' END] AS counts
 FROM raw.record r WHERE r.source_id = %(source_id)s AND r.resource_id = %(crash_resource_id)s AND r.file_sha256 = %(crash_file_sha256)s AND r.parser_version = %(crash_parser_version)s AND (r.payload ->> 'Year of crash')::integer BETWEEN %(year_from)s AND %(year_to)s
)
SELECT
 count(*) FILTER (WHERE severity IS NOT NULL AND NOT (%(severity_map)s::jsonb ? severity)),
 count(*) FILTER (WHERE EXISTS (
   SELECT 1 FROM unnest(counts) v WHERE v IS NOT NULL
   AND (v !~ '^[0-9]+$' OR NOT pg_input_is_valid(v, 'integer'))
 )),
 count(*) FILTER (WHERE array_position(counts, NULL) IS NULL AND (
   SELECT sum(CASE WHEN v ~ '^[0-9]+$' AND pg_input_is_valid(v, 'integer') THEN v::bigint END)
   FROM unnest(counts) v
 ) > 2147483647)
FROM native;
