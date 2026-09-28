-- D09 fixed-batch display context, version d09-0.1.1.
-- Deploy as arsia_migrator after migrations 001-011.

CREATE OR REPLACE FUNCTION published.d09_batch_sources(
    p_dataset_kind text,
    p_batch_id uuid
)
RETURNS TABLE (
    dataset_kind text,
    batch_id uuid,
    source_id text,
    source_name text,
    jurisdiction_code text,
    release_label text,
    release_scope text
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $d09_sources$
DECLARE
    v_kind text;
    v_status text;
BEGIN
    IF p_dataset_kind IS NULL
       OR p_dataset_kind NOT IN ('official', 'synthetic') THEN
        RAISE EXCEPTION 'D09_DATASET_KIND: expected official or synthetic'
            USING ERRCODE = '22023';
    END IF;
    SELECT candidate.dataset_kind, candidate.status
      INTO v_kind, v_status
      FROM meta.batch AS candidate
     WHERE candidate.batch_id = p_batch_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'D09_BATCH: unknown batch'
            USING ERRCODE = '22023';
    END IF;
    IF v_kind IS DISTINCT FROM p_dataset_kind THEN
        RAISE EXCEPTION 'D09_BATCH_MODE: batch belongs to another dataset kind'
            USING ERRCODE = '22023';
    END IF;
    IF v_status IS DISTINCT FROM 'succeeded' THEN
        RAISE EXCEPTION 'D09_BATCH_STATUS: batch is not succeeded'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    SELECT
        p_dataset_kind,
        p_batch_id,
        source.source_id,
        source.source_name,
        source.jurisdiction_code,
        source.release_label,
        source.release_scope
      FROM dw.dim_source AS source
     WHERE source.batch_id = p_batch_id
     ORDER BY source.source_id;
END;
$d09_sources$;

ALTER FUNCTION published.d09_batch_sources(text, uuid)
    OWNER TO arsia_migrator;
REVOKE ALL ON FUNCTION published.d09_batch_sources(text, uuid) FROM PUBLIC;
GRANT USAGE ON SCHEMA published TO arsia_loader;
GRANT EXECUTE ON FUNCTION published.d09_batch_sources(text, uuid)
    TO arsia_reader, arsia_loader;

COMMENT ON FUNCTION published.d09_batch_sources(text, uuid) IS
    'D09 d09-0.1.0: source and release labels for one explicit successful batch.';

CREATE OR REPLACE FUNCTION published.d09_batch_years(
    p_dataset_kind text,
    p_batch_id uuid
)
RETURNS TABLE (year_from integer, year_to integer)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $d09_years$
DECLARE
    v_kind text;
    v_status text;
    v_manifest jsonb;
BEGIN
    IF p_dataset_kind IS NULL
       OR p_dataset_kind NOT IN ('official', 'synthetic') THEN
        RAISE EXCEPTION 'D09_DATASET_KIND: expected official or synthetic'
            USING ERRCODE = '22023';
    END IF;
    SELECT candidate.dataset_kind, candidate.status, candidate.manifest
      INTO v_kind, v_status, v_manifest
      FROM meta.batch AS candidate
     WHERE candidate.batch_id = p_batch_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'D09_BATCH: unknown batch'
            USING ERRCODE = '22023';
    END IF;
    IF v_kind IS DISTINCT FROM p_dataset_kind THEN
        RAISE EXCEPTION 'D09_BATCH_MODE: batch belongs to another dataset kind'
            USING ERRCODE = '22023';
    END IF;
    IF v_status IS DISTINCT FROM 'succeeded' THEN
        RAISE EXCEPTION 'D09_BATCH_STATUS: batch is not succeeded'
            USING ERRCODE = '22023';
    END IF;
    year_from := (v_manifest #>> '{analysis,year_from}')::integer;
    year_to := (v_manifest #>> '{analysis,year_to}')::integer;
    IF year_from IS NULL OR year_to IS NULL
       OR year_from NOT BETWEEN 1 AND 9999
       OR year_to NOT BETWEEN 1 AND 9999
       OR year_from > year_to THEN
        RAISE EXCEPTION 'D09_YEAR_RANGE: invalid manifest year interval'
            USING ERRCODE = '22023';
    END IF;
    RETURN NEXT;
END;
$d09_years$;

ALTER FUNCTION published.d09_batch_years(text, uuid) OWNER TO arsia_migrator;
REVOKE ALL ON FUNCTION published.d09_batch_years(text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION published.d09_batch_years(text, uuid)
    TO arsia_reader, arsia_loader;

COMMENT ON FUNCTION published.d09_batch_years(text, uuid) IS
    'D09 d09-0.1.1: analysis years for one explicit successful batch.';
