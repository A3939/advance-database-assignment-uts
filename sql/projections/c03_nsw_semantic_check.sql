-- C03 NSW semantic validation.
-- Run after key/relationship checks and before projection inserts.

WITH crash_rows AS (
    SELECT
        r.payload ->> 'Degree of crash - detailed' AS severity_raw,
        r.payload ->> 'No. killed' AS killed_raw,
        r.payload ->> 'No. seriously injured' AS serious_raw,
        r.payload ->> 'No. moderately injured' AS moderate_raw,
        r.payload ->> 'No. minor-other injured' AS minor_other_raw
    FROM raw.record AS r
    WHERE r.source_id = %s
      AND r.resource_id = %s
      AND r.file_sha256 = %s
      AND r.parser_version = %s
      AND (r.payload ->> 'Year of crash')::integer
          BETWEEN 2020 AND 2024
)

SELECT
    COUNT(*) FILTER (
        WHERE severity_raw IS NOT NULL
          AND severity_raw NOT IN (
              'Fatal',
              'Serious Injury',
              'Moderate Injury',
              'Minor/Other Injury',
              'Uncategorised Injury',
              'Non-casualty (towaway)'
          )
    ) AS unknown_severity_count,

    COUNT(*) FILTER (
        WHERE killed_raw IS NOT NULL
          AND killed_raw !~ '^[0-9]+$'
    ) AS invalid_fatality_count,

    COUNT(*) FILTER (
        WHERE serious_raw IS NOT NULL
          AND serious_raw !~ '^[0-9]+$'
    ) AS invalid_serious_count,

    COUNT(*) FILTER (
        WHERE moderate_raw IS NOT NULL
          AND moderate_raw !~ '^[0-9]+$'
    ) AS invalid_moderate_count,

    COUNT(*) FILTER (
        WHERE minor_other_raw IS NOT NULL
          AND minor_other_raw !~ '^[0-9]+$'
    ) AS invalid_minor_other_count

FROM crash_rows;
