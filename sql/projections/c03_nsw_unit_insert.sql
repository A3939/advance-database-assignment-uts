-- C03 NSW Traffic Unit projection insert.
-- Full-snapshot relationship checks and unit-category checks
-- must already have passed before this statement is executed.

INSERT INTO pg_temp.arsia_i_unit (
    batch_id,
    source_id,
    release_scope,
    unit_key,
    crash_key,
    raw_record_id,
    unit_type_raw,
    unit_type_code,
    statistical_scope,
    count_eligible,
    quality_notes
)
SELECT
    %s::uuid AS batch_id,

    u.source_id,

    %s::text AS release_scope,

    rv.encode_business_key(
        u.payload ->> 'Crash ID',
        u.payload ->> 'Traffic unit ID'
    ) AS unit_key,

    rv.encode_business_key(
        u.payload ->> 'Crash ID'
    ) AS crash_key,

    u.raw_record_id,

    u.payload ->> 'TU type group'
        AS unit_type_raw,

    NULL::text AS unit_type_code,

    %s::text AS statistical_scope,

    (
        u.payload ->> 'TU type group' IS NOT NULL
        AND btrim(
            u.payload ->> 'TU type group'
        ) <> ''
    ) AS count_eligible,

    jsonb_strip_nulls(
        jsonb_build_object(
            'count',
                CASE
                    WHEN u.payload ->> 'TU type group'
                        IS NULL
                      OR btrim(
                            u.payload ->> 'TU type group'
                         ) = ''
                    THEN 'missing'
                    ELSE NULL
                END
        )
    ) AS quality_notes

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
      BETWEEN 2020 AND 2024;
