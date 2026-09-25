-- C07 VIC Node observations.
-- Preserve every selected native Node observation.
-- Do not deduplicate, choose a representative, or average coordinates here.

SELECT
    r.raw_record_id,
    r.source_id,
    r.resource_id,
    r.file_sha256,
    r.parser_version,
    r.row_locator,

    r.payload ->> 'ACCIDENT_NO'
        AS accident_no,

    r.payload ->> 'NODE_ID'
        AS node_id,

    r.payload ->> 'LATITUDE'
        AS latitude_raw,

    r.payload ->> 'LONGITUDE'
        AS longitude_raw,

    r.payload ->> 'DEG_URBAN_NAME'
        AS deg_urban_name

FROM raw.record AS r

WHERE r.source_id = %s
  AND r.resource_id = %s
  AND r.file_sha256 = %s
  AND r.parser_version = %s

ORDER BY
    r.payload ->> 'ACCIDENT_NO',
    r.payload ->> 'NODE_ID',
    r.file_sha256,
    r.parser_version,
    r.row_locator;
