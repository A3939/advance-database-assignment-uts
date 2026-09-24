-- C03 NSW occurrence-year validation.
-- Validate native year text before any integer cast is used.

SELECT COUNT(*) AS invalid_year_count
FROM raw.record AS r
WHERE r.source_id = %s
  AND r.resource_id = %s
  AND r.file_sha256 = %s
  AND r.parser_version = %s
  AND (
      r.payload ->> 'Year of crash' IS NULL
      OR r.payload ->> 'Year of crash' !~ '^[0-9]{4}$'
  );
