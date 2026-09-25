-- D06 L5 fixed-batch severity query, version d06-0.1.0.
-- Deploy as arsia_migrator after migrations 001-011.

CREATE OR REPLACE FUNCTION published.d06_severity(
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
    filter_year_from integer,
    filter_year_to integer,
    filter_months integer[],
    definition_version text,
    severity_code text,
    severity_label text,
    definition_text text,
    crash_count bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $d06$
DECLARE
    v_manifest jsonb;
    v_actual_kind text;
    v_status text;
    v_year_from integer;
    v_year_to integer;
BEGIN
    IF p_dataset_kind IS NULL
       OR p_dataset_kind NOT IN ('official', 'synthetic') THEN
        RAISE EXCEPTION 'D06_DATASET_KIND: expected official or synthetic'
            USING ERRCODE = '22023';
    END IF;

    SELECT candidate.dataset_kind, candidate.status, candidate.manifest
      INTO v_actual_kind, v_status, v_manifest
      FROM meta.batch AS candidate
     WHERE candidate.batch_id = p_batch_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'D06_BATCH: unknown batch'
            USING ERRCODE = '22023';
    END IF;
    IF v_actual_kind IS DISTINCT FROM p_dataset_kind THEN
        RAISE EXCEPTION 'D06_BATCH_MODE: batch belongs to another dataset kind'
            USING ERRCODE = '22023';
    END IF;
    IF v_status IS DISTINCT FROM 'succeeded' THEN
        RAISE EXCEPTION 'D06_BATCH_STATUS: batch is not succeeded'
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
        RAISE EXCEPTION 'D06_YEAR_RANGE: invalid year interval'
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
        RAISE EXCEPTION 'D06_MONTHS: use unique months from 1 to 12'
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
        RAISE EXCEPTION 'D06_SOURCES: use unique non-empty source IDs'
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
        RAISE EXCEPTION 'D06_SOURCE: source is not enabled for this batch'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT
        p_dataset_kind,
        p_batch_id,
        fact.source_id,
        v_year_from,
        v_year_to,
        p_months,
        severity.definition_version,
        fact.severity_code,
        severity.severity_label,
        severity.definition_text,
        count(*)::bigint
      FROM dw.fact_crash AS fact
      JOIN dw.dim_severity AS severity
        ON severity.batch_id = fact.batch_id
       AND severity.source_id = fact.source_id
       AND severity.severity_code = fact.severity_code
     WHERE fact.batch_id = p_batch_id
       AND fact.occurrence_year BETWEEN v_year_from AND v_year_to
       AND (p_source_ids IS NULL OR fact.source_id = ANY(p_source_ids))
       AND (
            p_months IS NULL
            OR (
                fact.month_id IS NOT NULL
                AND (fact.month_id % 100) = ANY(p_months)
            )
       )
     GROUP BY fact.source_id, severity.definition_version,
              fact.severity_code, severity.severity_label,
              severity.definition_text
     ORDER BY fact.source_id, severity.definition_version,
              fact.severity_code;
END;
$d06$;

ALTER FUNCTION published.d06_severity(
    text, uuid, text[], integer, integer, integer[]
) OWNER TO arsia_migrator;

REVOKE ALL ON FUNCTION published.d06_severity(
    text, uuid, text[], integer, integer, integer[]
) FROM PUBLIC;
GRANT USAGE ON SCHEMA published TO arsia_loader;
GRANT EXECUTE ON FUNCTION published.d06_severity(
    text, uuid, text[], integer, integer, integer[]
) TO arsia_reader, arsia_loader;

COMMENT ON FUNCTION published.d06_severity(
    text, uuid, text[], integer, integer, integer[]
) IS 'D06 d06-0.1.0: fixed successful-batch L5 source severity query.';
