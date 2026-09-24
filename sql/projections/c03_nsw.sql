-- C03 NSW projection
-- Step 1: select the exact frozen NSW Crash Raw rows.
-- Do not filter occurrence year here.

SELECT
    r.raw_record_id,
    r.source_id,
    r.resource_id,
    r.file_sha256,
    r.parser_version,
    r.row_locator,
    r.payload
FROM raw.record AS r
WHERE r.source_id = %s
  AND r.resource_id = %s
  AND r.file_sha256 = %s
  AND r.parser_version = %s;
