-- D08 fixed-batch basic-unit query, version d08-0.1.0.
-- Deploy as arsia_migrator after migrations 001-011.

CREATE OR REPLACE FUNCTION published.d08_validate_request(
    p_dataset_kind text,
    p_batch_id uuid,
    p_source_ids text[],
    p_year_from integer,
    p_year_to integer,
    p_months integer[]
)
RETURNS TABLE (year_from integer, year_to integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $d08_validate$
DECLARE
    v_manifest jsonb;
    v_actual_kind text;
    v_status text;
    v_year_from integer;
    v_year_to integer;
BEGIN
    IF p_dataset_kind IS NULL
       OR p_dataset_kind NOT IN ('official', 'synthetic') THEN
        RAISE EXCEPTION 'D08_DATASET_KIND: expected official or synthetic'
            USING ERRCODE = '22023';
    END IF;

    SELECT candidate.dataset_kind, candidate.status, candidate.manifest
      INTO v_actual_kind, v_status, v_manifest
      FROM meta.batch AS candidate
     WHERE candidate.batch_id = p_batch_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'D08_BATCH: unknown batch'
            USING ERRCODE = '22023';
    END IF;
    IF v_actual_kind IS DISTINCT FROM p_dataset_kind THEN
        RAISE EXCEPTION 'D08_BATCH_MODE: batch belongs to another dataset kind'
            USING ERRCODE = '22023';
    END IF;
    IF v_status IS DISTINCT FROM 'succeeded' THEN
        RAISE EXCEPTION 'D08_BATCH_STATUS: batch is not succeeded'
            USING ERRCODE = '22023';
    END IF;

    v_year_from := COALESCE(
        p_year_from, (v_manifest #>> '{analysis,year_from}')::integer
    );
    v_year_to := COALESCE(
        p_year_to, (v_manifest #>> '{analysis,year_to}')::integer
    );
    IF v_year_from IS NULL OR v_year_to IS NULL
       OR v_year_from NOT BETWEEN 1 AND 9999
       OR v_year_to NOT BETWEEN 1 AND 9999
       OR v_year_from > v_year_to THEN
        RAISE EXCEPTION 'D08_YEAR_RANGE: invalid year interval'
            USING ERRCODE = '22023';
    END IF;

    IF p_months IS NOT NULL AND (
        cardinality(p_months) = 0
        OR EXISTS (
            SELECT 1 FROM unnest(p_months) AS requested(month)
             WHERE requested.month IS NULL
                OR requested.month NOT BETWEEN 1 AND 12
        )
        OR cardinality(p_months) <> (
            SELECT count(DISTINCT requested.month)
              FROM unnest(p_months) AS requested(month)
        )
    ) THEN
        RAISE EXCEPTION 'D08_MONTHS: use unique months from 1 to 12'
            USING ERRCODE = '22023';
    END IF;

    IF p_source_ids IS NOT NULL AND (
        cardinality(p_source_ids) = 0
        OR EXISTS (
            SELECT 1 FROM unnest(p_source_ids) AS requested(value)
             WHERE requested.value IS NULL OR btrim(requested.value) = ''
        )
        OR cardinality(p_source_ids) <> (
            SELECT count(DISTINCT requested.value)
              FROM unnest(p_source_ids) AS requested(value)
        )
    ) THEN
        RAISE EXCEPTION 'D08_SOURCES: use unique non-empty source IDs'
            USING ERRCODE = '22023';
    END IF;
    IF p_source_ids IS NOT NULL AND EXISTS (
        SELECT 1
          FROM unnest(p_source_ids) AS requested(value)
         WHERE NOT EXISTS (
            SELECT 1
              FROM dw.dim_source AS source
             WHERE source.batch_id = p_batch_id
               AND source.source_id = requested.value
         )
    ) THEN
        RAISE EXCEPTION 'D08_SOURCE: source is not enabled for this batch'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY SELECT v_year_from, v_year_to;
END;
$d08_validate$;

CREATE OR REPLACE FUNCTION published.d08_unit_counts(
    p_dataset_kind text,
    p_batch_id uuid,
    p_source_ids text[] DEFAULT NULL,
    p_year_from integer DEFAULT NULL,
    p_year_to integer DEFAULT NULL,
    p_months integer[] DEFAULT NULL
)
RETURNS TABLE (
    dataset_kind text,
    batch_id uuid,
    source_id text,
    source_name text,
    jurisdiction_code text,
    statistical_scope text,
    unit_type_code text,
    unit_count bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $d08_counts$
DECLARE
    v_year_from integer;
    v_year_to integer;
BEGIN
    SELECT bounds.year_from, bounds.year_to
      INTO STRICT v_year_from, v_year_to
      FROM published.d08_validate_request(
               p_dataset_kind, p_batch_id, p_source_ids,
               p_year_from, p_year_to, p_months
           ) AS bounds;

    RETURN QUERY
    -- Read each parent once, even before statistics catch up with a new build.
    WITH members AS (
        SELECT parent.batch_id, parent.source_id, parent.release_scope, parent.crash_key,
               NULL::text AS statistical_scope, NULL::text AS unit_type_code,
               true AS parent_row
          FROM dw.fact_crash AS parent
         WHERE parent.batch_id = p_batch_id
           AND parent.occurrence_year BETWEEN v_year_from AND v_year_to
           AND (p_source_ids IS NULL OR parent.source_id = ANY(p_source_ids))
           AND (
                p_months IS NULL
                OR (
                    parent.month_id IS NOT NULL
                    AND (parent.month_id % 100) = ANY(p_months)
                )
           )
        UNION ALL
        SELECT unit.batch_id, unit.source_id, unit.release_scope, unit.crash_key,
               unit.statistical_scope, unit.unit_type_code, false
          FROM canonical.unit AS unit
         WHERE unit.batch_id = p_batch_id
           AND unit.count_eligible
           AND (p_source_ids IS NULL OR unit.source_id = ANY(p_source_ids))
    ), membership AS (
        SELECT members.*,
               bool_or(members.parent_row) OVER (
                   PARTITION BY members.batch_id, members.source_id,
                                members.release_scope, members.crash_key
               ) AS has_parent
          FROM members
    ), unit_counts AS (
        SELECT member.batch_id, member.source_id, member.statistical_scope,
               member.unit_type_code, count(*)::bigint AS unit_count
          FROM membership AS member
         WHERE NOT member.parent_row AND member.has_parent
         GROUP BY member.batch_id, member.source_id,
                  member.statistical_scope, member.unit_type_code
    )
    SELECT
        p_dataset_kind,
        p_batch_id,
        unit.source_id,
        source.source_name,
        source.jurisdiction_code,
        unit.statistical_scope,
        unit.unit_type_code,
        unit.unit_count
      FROM unit_counts AS unit
      JOIN dw.dim_source AS source
        ON source.batch_id = unit.batch_id
       AND source.source_id = unit.source_id
     ORDER BY
        unit.source_id,
        unit.statistical_scope,
        unit.unit_type_code;
END;
$d08_counts$;

ALTER FUNCTION published.d08_validate_request(
    text, uuid, text[], integer, integer, integer[]
) OWNER TO arsia_migrator;
ALTER FUNCTION published.d08_unit_counts(
    text, uuid, text[], integer, integer, integer[]
) OWNER TO arsia_migrator;

REVOKE ALL ON FUNCTION published.d08_validate_request(
    text, uuid, text[], integer, integer, integer[]
) FROM PUBLIC;
REVOKE ALL ON FUNCTION published.d08_unit_counts(
    text, uuid, text[], integer, integer, integer[]
) FROM PUBLIC;

GRANT USAGE ON SCHEMA published TO arsia_loader;
GRANT EXECUTE ON FUNCTION published.d08_unit_counts(
    text, uuid, text[], integer, integer, integer[]
) TO arsia_reader, arsia_loader;

COMMENT ON FUNCTION published.d08_unit_counts(
    text, uuid, text[], integer, integer, integer[]
) IS 'D08 d08-0.1.0: eligible units grouped within each source statistical scope and type.';
