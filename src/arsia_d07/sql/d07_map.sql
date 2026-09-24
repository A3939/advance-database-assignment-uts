-- D07 fixed-batch map points and coverage, version d07-0.1.0.
-- Deploy as arsia_migrator after migrations 001-011.

CREATE OR REPLACE FUNCTION published.d07_validate_request(
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
AS $d07_validate$
DECLARE
    v_manifest jsonb;
    v_actual_kind text;
    v_status text;
    v_year_from integer;
    v_year_to integer;
BEGIN
    IF p_dataset_kind IS NULL
       OR p_dataset_kind NOT IN ('official', 'synthetic') THEN
        RAISE EXCEPTION 'D07_DATASET_KIND: expected official or synthetic'
            USING ERRCODE = '22023';
    END IF;

    SELECT candidate.dataset_kind, candidate.status, candidate.manifest
      INTO v_actual_kind, v_status, v_manifest
      FROM meta.batch AS candidate
     WHERE candidate.batch_id = p_batch_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'D07_BATCH: unknown batch'
            USING ERRCODE = '22023';
    END IF;
    IF v_actual_kind IS DISTINCT FROM p_dataset_kind THEN
        RAISE EXCEPTION 'D07_BATCH_MODE: batch belongs to another dataset kind'
            USING ERRCODE = '22023';
    END IF;
    IF v_status IS DISTINCT FROM 'succeeded' THEN
        RAISE EXCEPTION 'D07_BATCH_STATUS: batch is not succeeded'
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
        RAISE EXCEPTION 'D07_YEAR_RANGE: invalid year interval'
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
        RAISE EXCEPTION 'D07_MONTHS: use unique months from 1 to 12'
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
        RAISE EXCEPTION 'D07_SOURCES: use unique non-empty source IDs'
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
        RAISE EXCEPTION 'D07_SOURCE: source is not enabled for this batch'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY SELECT v_year_from, v_year_to;
END;
$d07_validate$;

CREATE OR REPLACE FUNCTION published.d07_map_points(
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
    release_scope text,
    crash_key text,
    occurrence_year integer,
    occurrence_month integer,
    severity_code text,
    latitude numeric,
    longitude numeric
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $d07_points$
    SELECT
        p_dataset_kind,
        p_batch_id,
        fact.source_id,
        source.source_name,
        source.jurisdiction_code,
        fact.release_scope,
        fact.crash_key,
        fact.occurrence_year,
        CASE WHEN fact.month_id IS NULL THEN NULL ELSE fact.month_id % 100 END,
        fact.severity_code,
        fact.latitude,
        fact.longitude
      FROM published.d07_validate_request(
               p_dataset_kind, p_batch_id, p_source_ids,
               p_year_from, p_year_to, p_months
           ) AS bounds
      JOIN dw.fact_crash AS fact
        ON fact.batch_id = p_batch_id
       AND fact.occurrence_year BETWEEN bounds.year_from AND bounds.year_to
      JOIN dw.dim_source AS source
        ON source.batch_id = fact.batch_id
       AND source.source_id = fact.source_id
     WHERE fact.map_eligible
       AND fact.latitude IS NOT NULL
       AND fact.longitude IS NOT NULL
       AND (p_source_ids IS NULL OR fact.source_id = ANY(p_source_ids))
       AND (
            p_months IS NULL
            OR (
                fact.month_id IS NOT NULL
                AND (fact.month_id % 100) = ANY(p_months)
            )
       )
     ORDER BY fact.source_id, fact.release_scope, fact.crash_key;
$d07_points$;

CREATE OR REPLACE FUNCTION published.d07_map_coverage(
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
    filter_source_ids text[],
    filter_year_from integer,
    filter_year_to integer,
    filter_months integer[],
    crash_count bigint,
    point_count bigint,
    coverage_percentage numeric
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $d07_coverage$
    SELECT
        p_dataset_kind,
        p_batch_id,
        p_source_ids,
        bounds.year_from,
        bounds.year_to,
        p_months,
        count(fact.crash_key)::bigint,
        count(fact.crash_key) FILTER (
            WHERE fact.map_eligible
              AND fact.latitude IS NOT NULL
              AND fact.longitude IS NOT NULL
        )::bigint,
        CASE
            WHEN count(fact.crash_key) = 0 THEN NULL
            ELSE round(
                100.0 * count(fact.crash_key) FILTER (
                    WHERE fact.map_eligible
                      AND fact.latitude IS NOT NULL
                      AND fact.longitude IS NOT NULL
                ) / count(fact.crash_key),
                2
            )
        END
      FROM published.d07_validate_request(
               p_dataset_kind, p_batch_id, p_source_ids,
               p_year_from, p_year_to, p_months
           ) AS bounds
      LEFT JOIN dw.fact_crash AS fact
        ON fact.batch_id = p_batch_id
       AND fact.occurrence_year BETWEEN bounds.year_from AND bounds.year_to
       AND (p_source_ids IS NULL OR fact.source_id = ANY(p_source_ids))
       AND (
            p_months IS NULL
            OR (
                fact.month_id IS NOT NULL
                AND (fact.month_id % 100) = ANY(p_months)
            )
       )
     GROUP BY bounds.year_from, bounds.year_to;
$d07_coverage$;

ALTER FUNCTION published.d07_validate_request(
    text, uuid, text[], integer, integer, integer[]
) OWNER TO arsia_migrator;
ALTER FUNCTION published.d07_map_points(
    text, uuid, text[], integer, integer, integer[]
) OWNER TO arsia_migrator;
ALTER FUNCTION published.d07_map_coverage(
    text, uuid, text[], integer, integer, integer[]
) OWNER TO arsia_migrator;

REVOKE ALL ON FUNCTION published.d07_validate_request(
    text, uuid, text[], integer, integer, integer[]
) FROM PUBLIC;
REVOKE ALL ON FUNCTION published.d07_map_points(
    text, uuid, text[], integer, integer, integer[]
) FROM PUBLIC;
REVOKE ALL ON FUNCTION published.d07_map_coverage(
    text, uuid, text[], integer, integer, integer[]
) FROM PUBLIC;

GRANT USAGE ON SCHEMA published TO arsia_loader;
GRANT EXECUTE ON FUNCTION published.d07_map_points(
    text, uuid, text[], integer, integer, integer[]
) TO arsia_reader, arsia_loader;
GRANT EXECUTE ON FUNCTION published.d07_map_coverage(
    text, uuid, text[], integer, integer, integer[]
) TO arsia_reader, arsia_loader;

COMMENT ON FUNCTION published.d07_map_points(
    text, uuid, text[], integer, integer, integer[]
) IS 'D07 d07-0.1.0: one eligible point per complete crash identity.';
COMMENT ON FUNCTION published.d07_map_coverage(
    text, uuid, text[], integer, integer, integer[]
) IS 'D07 d07-0.1.0: SQL crash count, point count and coverage percentage.';
