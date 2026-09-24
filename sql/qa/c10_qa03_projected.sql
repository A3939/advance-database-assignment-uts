-- C10 QA03_PROJECTED
--
-- One call evaluates one projected crash or unit resource.
--
-- Parameter:
-- {
--   "entity_kind": "crash" | "unit",
--   "batch_id": "...uuid...",
--   "source_id": "...",
--   "release_scope": "...",
--   "input_count": 123,
--   "excluded_count": 23
-- }
--
-- input_count and excluded_count must be independently derived
-- from the frozen input/source rules. They must not be inferred
-- from the projection being tested.

WITH params AS (
    SELECT
        %s::jsonb AS p
),

rules AS (
    SELECT
        p ->> 'entity_kind'
            AS entity_kind,

        (p ->> 'batch_id')::uuid
            AS batch_id,

        p ->> 'source_id'
            AS source_id,

        p ->> 'release_scope'
            AS release_scope,

        (p ->> 'input_count')::bigint
            AS input_count,

        (p ->> 'excluded_count')::bigint
            AS excluded_count

    FROM params
),

crash_rows AS (
    SELECT c.*
    FROM pg_temp.arsia_i_crash AS c
    CROSS JOIN rules AS r

    WHERE r.entity_kind = 'crash'
      AND c.batch_id = r.batch_id
      AND c.source_id = r.source_id
      AND c.release_scope = r.release_scope
),

unit_rows AS (
    SELECT u.*
    FROM pg_temp.arsia_i_unit AS u
    CROSS JOIN rules AS r

    WHERE r.entity_kind = 'unit'
      AND u.batch_id = r.batch_id
      AND u.source_id = r.source_id
      AND u.release_scope = r.release_scope
),

projected_count AS (
    SELECT
        CASE
            WHEN r.entity_kind = 'crash'
                THEN (
                    SELECT COUNT(*)
                    FROM crash_rows
                )

            WHEN r.entity_kind = 'unit'
                THEN (
                    SELECT COUNT(*)
                    FROM unit_rows
                )

            ELSE NULL
        END::bigint AS value

    FROM rules AS r
),

duplicate_key_count AS (
    SELECT
        CASE
            WHEN r.entity_kind = 'crash'
                THEN (
                    SELECT COUNT(*)
                    FROM (
                        SELECT crash_key
                        FROM crash_rows
                        GROUP BY crash_key
                        HAVING COUNT(*) > 1
                    ) AS duplicate_crashes
                )

            WHEN r.entity_kind = 'unit'
                THEN (
                    SELECT COUNT(*)
                    FROM (
                        SELECT unit_key
                        FROM unit_rows
                        GROUP BY unit_key
                        HAVING COUNT(*) > 1
                    ) AS duplicate_units
                )

            ELSE NULL
        END::bigint AS value

    FROM rules AS r
),

orphan_count AS (
    SELECT
        CASE
            WHEN r.entity_kind = 'crash'
                THEN 0

            WHEN r.entity_kind = 'unit'
                THEN (
                    SELECT COUNT(*)

                    FROM unit_rows AS u

                    LEFT JOIN pg_temp.arsia_i_crash AS c
                      ON c.batch_id = u.batch_id
                     AND c.source_id = u.source_id
                     AND c.release_scope = u.release_scope
                     AND c.crash_key = u.crash_key

                    WHERE c.crash_key IS NULL
                )

            ELSE NULL
        END::bigint AS value

    FROM rules AS r
),

invalid_value_count AS (
    SELECT
        CASE
            WHEN r.entity_kind = 'crash'
                THEN (
                    SELECT COUNT(*)

                    FROM crash_rows AS c

                    WHERE
                        c.crash_key IS NULL
                        OR btrim(c.crash_key) = ''

                        OR c.occurrence_year
                           NOT BETWEEN 1900 AND 2100

                        OR c.date_precision
                           NOT IN ('year', 'month', 'day')

                        OR (
                            c.date_precision = 'year'
                            AND (
                                c.occurrence_month IS NOT NULL
                                OR c.occurrence_date IS NOT NULL
                            )
                        )

                        OR (
                            c.date_precision = 'month'
                            AND (
                                c.occurrence_month IS NULL
                                OR c.occurrence_month
                                   NOT BETWEEN 1 AND 12
                                OR c.occurrence_date IS NOT NULL
                            )
                        )

                        OR (
                            c.date_precision = 'day'
                            AND (
                                c.occurrence_month IS NULL
                                OR c.occurrence_month
                                   NOT BETWEEN 1 AND 12
                                OR c.occurrence_date IS NULL
                                OR EXTRACT(
                                    YEAR FROM c.occurrence_date
                                ) <> c.occurrence_year
                                OR EXTRACT(
                                    MONTH FROM c.occurrence_date
                                ) <> c.occurrence_month
                            )
                        )

                        OR c.severity_code IS NULL
                        OR btrim(c.severity_code) = ''

                        OR c.severity_definition_version IS NULL
                        OR btrim(
                            c.severity_definition_version
                        ) = ''

                        OR c.fatality_count < 0
                        OR c.casualty_count < 0

                        OR (
                            c.fatal_crash_eligible
                            AND c.is_fatal_crash IS NULL
                        )

                        OR (
                            c.fatality_eligible
                            AND c.fatality_count IS NULL
                        )

                        OR (
                            c.casualty_eligible
                            AND c.casualty_count IS NULL
                        )

                        OR jsonb_typeof(
                            c.quality_notes
                        ) <> 'object'
                )

            WHEN r.entity_kind = 'unit'
                THEN (
                    SELECT COUNT(*)

                    FROM unit_rows AS u

                    WHERE
                        u.unit_key IS NULL
                        OR btrim(u.unit_key) = ''

                        OR u.crash_key IS NULL
                        OR btrim(u.crash_key) = ''

                        OR u.statistical_scope IS NULL
                        OR btrim(u.statistical_scope) = ''

                        OR (
                            u.count_eligible
                            AND (
                                u.unit_type_code IS NULL
                                OR btrim(
                                    u.unit_type_code
                                ) = ''
                            )
                        )

                        OR jsonb_typeof(
                            u.quality_notes
                        ) <> 'object'
                )

            ELSE NULL
        END::bigint AS value

    FROM rules AS r
)

SELECT
    r.entity_kind,

    r.input_count,

    r.excluded_count,

    (
        r.input_count
        - r.excluded_count
    ) AS expected_projected_count,

    pc.value
        AS projected_count,

    dk.value
        AS duplicate_key_count,

    oc.value
        AS orphan_count,

    iv.value
        AS invalid_value_count,

    (
        pc.value
        = r.input_count - r.excluded_count
    ) AS projected_count_match

FROM rules AS r
CROSS JOIN projected_count AS pc
CROSS JOIN duplicate_key_count AS dk
CROSS JOIN orphan_count AS oc
CROSS JOIN invalid_value_count AS iv;
