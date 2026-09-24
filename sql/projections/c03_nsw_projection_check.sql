-- C03 NSW projection reconciliation.
-- Run after both pg_temp projection tables have been populated.

SELECT
    (
        SELECT COUNT(*)
        FROM pg_temp.arsia_i_crash
        WHERE batch_id = %s::uuid
          AND source_id = %s
          AND release_scope = %s
    ) AS crash_projection_count,

    (
        SELECT COUNT(*)
        FROM pg_temp.arsia_i_unit
        WHERE batch_id = %s::uuid
          AND source_id = %s
          AND release_scope = %s
    ) AS unit_projection_count,

    (
        SELECT COUNT(*)
        FROM (
            SELECT crash_key
            FROM pg_temp.arsia_i_crash
            GROUP BY crash_key
            HAVING COUNT(*) > 1
        ) AS d
    ) AS duplicate_crash_key_count,

    (
        SELECT COUNT(*)
        FROM (
            SELECT unit_key
            FROM pg_temp.arsia_i_unit
            GROUP BY unit_key
            HAVING COUNT(*) > 1
        ) AS d
    ) AS duplicate_unit_key_count,

    (
        SELECT COUNT(*)
        FROM pg_temp.arsia_i_unit AS u
        LEFT JOIN pg_temp.arsia_i_crash AS c
          ON c.crash_key = u.crash_key
         AND c.batch_id = u.batch_id
         AND c.source_id = u.source_id
         AND c.release_scope = u.release_scope
        WHERE c.crash_key IS NULL
    ) AS orphan_projected_unit_count,

    (
        SELECT COUNT(*)
        FROM pg_temp.arsia_i_crash
        WHERE is_fatal_crash IS TRUE
          AND fatal_crash_eligible IS TRUE
    ) AS fatal_crash_count,

    (
        SELECT COALESCE(SUM(fatality_count), 0)
        FROM pg_temp.arsia_i_crash
        WHERE fatality_eligible IS TRUE
    ) AS fatality_count,

    (
        SELECT COALESCE(SUM(casualty_count), 0)
        FROM pg_temp.arsia_i_crash
        WHERE casualty_eligible IS TRUE
    ) AS casualty_count,

    (
        SELECT COUNT(*)
        FROM pg_temp.arsia_i_crash
        WHERE map_eligible IS TRUE
    ) AS map_eligible_count;
