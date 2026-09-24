-- C03 NSW Crash projection insert.
-- All key, relationship, year, month and semantic checks
-- must pass before this statement is executed.

INSERT INTO pg_temp.arsia_i_crash (
    batch_id,
    source_id,
    release_scope,
    crash_key,
    raw_record_id,
    occurrence_year,
    occurrence_month,
    occurrence_date,
    date_precision,
    severity_raw,
    severity_code,
    severity_definition_version,
    is_fatal_crash,
    fatality_count,
    casualty_count,
    fatal_crash_eligible,
    fatality_eligible,
    casualty_eligible,
    latitude,
    longitude,
    location_crs,
    map_eligible,
    location_record_id,
    quality_notes
)
SELECT
    %s::uuid AS batch_id,

    r.source_id,

    %s::text AS release_scope,

    rv.encode_business_key(
        r.payload ->> 'Crash ID'
    ) AS crash_key,

    r.raw_record_id,

    (r.payload ->> 'Year of crash')::integer
        AS occurrence_year,

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
        WHEN r.payload ->> 'Month of crash' IS NULL
            THEN 'year'
        ELSE 'month'
    END AS date_precision,

    r.payload ->> 'Degree of crash - detailed'
        AS severity_raw,

    CASE r.payload ->> 'Degree of crash - detailed'
        WHEN 'Fatal'
            THEN 'FATAL'
        WHEN 'Serious Injury'
            THEN 'SERIOUS_INJURY'
        WHEN 'Moderate Injury'
            THEN 'MODERATE_INJURY'
        WHEN 'Minor/Other Injury'
            THEN 'MINOR_OTHER_INJURY'
        WHEN 'Uncategorised Injury'
            THEN 'UNCATEGORISED_INJURY'
        WHEN 'Non-casualty (towaway)'
            THEN 'NON_CASUALTY_TOWAWAY'
        WHEN NULL
            THEN '__MISSING__'
        ELSE '__MISSING__'
    END AS severity_code,

    %s::text AS severity_definition_version,

    CASE
        WHEN r.payload ->> 'Degree of crash - detailed'
            = 'Fatal'
            THEN TRUE

        WHEN r.payload ->> 'Degree of crash - detailed'
            IN (
                'Serious Injury',
                'Moderate Injury',
                'Minor/Other Injury',
                'Uncategorised Injury',
                'Non-casualty (towaway)'
            )
            THEN FALSE

        ELSE NULL
    END AS is_fatal_crash,

    CASE
        WHEN r.payload ->> 'No. killed' IS NULL
            THEN NULL
        ELSE
            (r.payload ->> 'No. killed')::integer
    END AS fatality_count,

    CASE
        WHEN r.payload ->> 'No. killed' IS NULL
          OR r.payload ->> 'No. seriously injured' IS NULL
          OR r.payload ->> 'No. moderately injured' IS NULL
          OR r.payload ->> 'No. minor-other injured' IS NULL
            THEN NULL
        ELSE
              (r.payload ->> 'No. killed')::integer
            + (r.payload ->> 'No. seriously injured')::integer
            + (r.payload ->> 'No. moderately injured')::integer
            + (r.payload ->> 'No. minor-other injured')::integer
    END AS casualty_count,

    (
        r.payload ->> 'Degree of crash - detailed'
        IS NOT NULL
    ) AS fatal_crash_eligible,

    (
        r.payload ->> 'No. killed'
        IS NOT NULL
    ) AS fatality_eligible,

    (
        r.payload ->> 'No. killed' IS NOT NULL
        AND r.payload ->> 'No. seriously injured' IS NOT NULL
        AND r.payload ->> 'No. moderately injured' IS NOT NULL
        AND r.payload ->> 'No. minor-other injured' IS NOT NULL
    ) AS casualty_eligible,

    NULL::numeric(10,7) AS latitude,

    NULL::numeric(10,7) AS longitude,

    NULL::text AS location_crs,

    FALSE AS map_eligible,

    NULL::uuid AS location_record_id,

    jsonb_strip_nulls(
        jsonb_build_object(
            'fatal_crash',
                CASE
                    WHEN r.payload ->> 'Degree of crash - detailed'
                        IS NULL
                    THEN 'missing'
                    ELSE NULL
                END,

            'fatality',
                CASE
                    WHEN r.payload ->> 'No. killed'
                        IS NULL
                    THEN 'missing'
                    ELSE NULL
                END,

            'casualty',
                CASE
                    WHEN r.payload ->> 'No. killed' IS NULL
                      OR r.payload ->> 'No. seriously injured' IS NULL
                      OR r.payload ->> 'No. moderately injured' IS NULL
                      OR r.payload ->> 'No. minor-other injured' IS NULL
                    THEN 'missing'
                    ELSE NULL
                END,

            'location',
                'crs_unconfirmed'
        )
    ) AS quality_notes

FROM raw.record AS r

WHERE r.source_id = %s
  AND r.resource_id = %s
  AND r.file_sha256 = %s
  AND r.parser_version = %s

  AND (r.payload ->> 'Year of crash')::integer
      BETWEEN 2020 AND 2024;
