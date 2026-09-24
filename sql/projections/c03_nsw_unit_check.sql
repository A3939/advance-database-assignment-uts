-- C03 NSW Traffic Unit semantic validation.
-- Run on the selected 2020-2024 parent scope before unit projection.

WITH selected_units AS (
    SELECT
        u.payload ->> 'TU type group' AS unit_type_raw
    FROM raw.record AS u
    JOIN raw.record AS c
      ON c.source_id = %s
     AND c.resource_id = %s
     AND c.file_sha256 = %s
     AND c.parser_version = %s
     AND c.payload ->> 'Crash ID'
         = u.payload ->> 'Crash ID'
    WHERE u.source_id = %s
      AND u.resource_id = %s
      AND u.file_sha256 = %s
      AND u.parser_version = %s
      AND (c.payload ->> 'Year of crash')::integer
          BETWEEN 2020 AND 2024
)

SELECT
    COUNT(*) FILTER (
        WHERE unit_type_raw IS NULL
           OR btrim(unit_type_raw) = ''
    ) AS missing_unit_type_count,

    COUNT(*) FILTER (
        WHERE unit_type_raw IS NOT NULL
          AND btrim(unit_type_raw) <> ''
          AND unit_type_raw NOT IN (
              'Car/car derivative',
              'Light truck',
              'Heavy rigid truck',
              'Articulated truck',
              'Bus',
              'Other motor vehicle',
              'Motorcycle',
              'Pedal cycle',
              'Non-motorised vehicle',
              'Pedestrian',
              'Other or unknown'
          )
    ) AS unknown_unit_type_count

FROM selected_units;
