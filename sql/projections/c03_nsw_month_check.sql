-- C03 NSW month validation.
-- Native NULL is the only declared missing month.
-- Any other non-NULL value must be one of the 12 registered English months.

SELECT COUNT(*) AS unknown_month_count
FROM raw.record AS r
WHERE r.source_id = %s
  AND r.resource_id = %s
  AND r.file_sha256 = %s
  AND r.parser_version = %s
  AND r.payload ->> 'Month of crash' IS NOT NULL
  AND r.payload ->> 'Month of crash' NOT IN (
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
  );
