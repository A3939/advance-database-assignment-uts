-- Legacy partial inspection query; use nsw.project for the complete C01 rowset.
-- Parameters: batch, release, source, resource, hash, parser, year_from, year_to.
-- Relationship validation must already have passed before this query runs.

SELECT
    %s::uuid AS batch_id,
    r.source_id,
    %s::text AS release_scope,

    rv.encode_business_key(
        r.payload ->> 'Crash ID'
    ) AS crash_key,

    r.raw_record_id,

    (r.payload ->> 'Year of crash')::integer AS occurrence_year,

    CASE r.payload ->> 'Month of crash'
        WHEN 'January' THEN 1
        WHEN 'February' THEN 2
        WHEN 'March' THEN 3
        WHEN 'April' THEN 4
        WHEN 'May' THEN 5
        WHEN 'June' THEN 6
        WHEN 'July' THEN 7
        WHEN 'August' THEN 8
        WHEN 'September' THEN 9
        WHEN 'October' THEN 10
        WHEN 'November' THEN 11
        WHEN 'December' THEN 12
        ELSE NULL
    END AS occurrence_month,

    NULL::date AS occurrence_date,

    CASE
        WHEN r.payload ->> 'Month of crash' IN (
            'January',
            'February',
            'March',
            'April',
            'May',
            'June',
            'July',
            'August',
            'September',
            'October',
            'November',
            'December'
        )
        THEN 'month'
        ELSE 'year'
    END AS date_precision

FROM raw.record AS r

WHERE r.source_id = %s
  AND r.resource_id = %s
  AND r.file_sha256 = %s
  AND r.parser_version = %s

  AND (r.payload ->> 'Year of crash')::integer
      BETWEEN %s AND %s;
