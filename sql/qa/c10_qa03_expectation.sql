-- C10 QA03 independent expectation derivation.
--
-- This query reads Raw + frozen file identities only.
-- It must not read pg_temp.arsia_i_crash / arsia_i_unit.

WITH params AS (
    SELECT %s::jsonb AS p
),

cfg AS (
    SELECT
        p ->> 'source_id'
            AS source_id,

        p ->> 'entity_kind'
            AS entity_kind,

        p ->> 'resource_id'
            AS resource_id,

        p ->> 'file_sha256'
            AS file_sha256,

        p ->> 'parser_version'
            AS parser_version,

        p ->> 'parent_resource_id'
            AS parent_resource_id,

        p ->> 'parent_file_sha256'
            AS parent_file_sha256,

        p ->> 'parent_parser_version'
            AS parent_parser_version,

        (p ->> 'year_from')::integer
            AS year_from,

        (p ->> 'year_to')::integer
            AS year_to

    FROM params
),

input_rows AS (
    SELECT
        r.raw_record_id,
        r.payload

    FROM raw.record AS r
    CROSS JOIN cfg AS c

    WHERE r.source_id = c.source_id
      AND r.resource_id = c.resource_id
      AND r.file_sha256 = c.file_sha256
      AND r.parser_version = c.parser_version
),

parent_rows AS (
    SELECT
        r.raw_record_id,
        r.payload

    FROM raw.record AS r
    CROSS JOIN cfg AS c

    WHERE r.source_id = c.source_id
      AND r.resource_id = c.parent_resource_id
      AND r.file_sha256 = c.parent_file_sha256
      AND r.parser_version = c.parent_parser_version
),

actual_input AS (
    SELECT COUNT(*)::bigint AS input_count
    FROM input_rows
),

excluded AS (
    SELECT
        CASE

            -- NSW Crash:
            -- valid occurrence year outside configured scope.
            WHEN c.source_id = 'official_nsw'
             AND c.entity_kind = 'crash'
            THEN (
                SELECT COUNT(*)::bigint
                FROM input_rows AS i

                WHERE i.payload ->> 'Year of crash'
                      ~ '^[0-9]{4}$'

                  AND (
                        (i.payload ->> 'Year of crash')::integer
                        < c.year_from

                        OR

                        (i.payload ->> 'Year of crash')::integer
                        > c.year_to
                  )
            )

            -- NSW Traffic Unit:
            -- resolve against complete Crash snapshot first,
            -- then inherit the parent's occurrence year.
            WHEN c.source_id = 'official_nsw'
             AND c.entity_kind = 'unit'
            THEN (
                SELECT COUNT(*)::bigint

                FROM input_rows AS u

                JOIN parent_rows AS p
                  ON p.payload ->> 'Crash ID'
                   = u.payload ->> 'Crash ID'

                WHERE p.payload ->> 'Year of crash'
                      ~ '^[0-9]{4}$'

                  AND (
                        (p.payload ->> 'Year of crash')::integer
                        < c.year_from

                        OR

                        (p.payload ->> 'Year of crash')::integer
                        > c.year_to
                  )
            )

            -- VIC Accident:
            -- valid ACCIDENT_DATE outside configured scope.
            WHEN c.source_id = 'official_vic'
             AND c.entity_kind = 'crash'
            THEN (
                SELECT COUNT(*)::bigint

                FROM input_rows AS i

                WHERE NULLIF(
                          btrim(
                              i.payload ->> 'ACCIDENT_DATE'
                          ),
                          ''
                      ) IS NOT NULL

                  AND pg_input_is_valid(
                          i.payload ->> 'ACCIDENT_DATE',
                          'date'
                      )

                  AND (
                        EXTRACT(
                            YEAR FROM
                            (i.payload ->> 'ACCIDENT_DATE')::date
                        )::integer
                        < c.year_from

                        OR

                        EXTRACT(
                            YEAR FROM
                            (i.payload ->> 'ACCIDENT_DATE')::date
                        )::integer
                        > c.year_to
                  )
            )

            -- VIC Vehicle:
            -- resolve the full Accident parent first,
            -- then inherit ACCIDENT_DATE.
            WHEN c.source_id = 'official_vic'
             AND c.entity_kind = 'unit'
            THEN (
                SELECT COUNT(*)::bigint

                FROM input_rows AS u

                JOIN parent_rows AS p
                  ON p.payload ->> 'ACCIDENT_NO'
                   = u.payload ->> 'ACCIDENT_NO'

                WHERE NULLIF(
                          btrim(
                              p.payload ->> 'ACCIDENT_DATE'
                          ),
                          ''
                      ) IS NOT NULL

                  AND pg_input_is_valid(
                          p.payload ->> 'ACCIDENT_DATE',
                          'date'
                      )

                  AND (
                        EXTRACT(
                            YEAR FROM
                            (p.payload ->> 'ACCIDENT_DATE')::date
                        )::integer
                        < c.year_from

                        OR

                        EXTRACT(
                            YEAR FROM
                            (p.payload ->> 'ACCIDENT_DATE')::date
                        )::integer
                        > c.year_to
                  )
            )

            ELSE NULL

        END AS excluded_count

    FROM cfg AS c
)

SELECT
    a.input_count,
    e.excluded_count

FROM actual_input AS a
CROSS JOIN excluded AS e;
