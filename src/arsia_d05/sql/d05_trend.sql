-- D05 L5 fixed-batch source/year/month trend query, version d05-0.1.0.
-- Deploy as arsia_migrator after migrations 001-011.

CREATE OR REPLACE FUNCTION published.d05_trend(
    p_dataset_kind text,
    p_batch_id uuid,
    p_grain text DEFAULT 'year',
    p_source_ids text[] DEFAULT NULL,
    p_year_from integer DEFAULT NULL,
    p_year_to integer DEFAULT NULL,
    p_months integer[] DEFAULT NULL
)
RETURNS TABLE (
    dataset_kind text,
    batch_id uuid,
    source_id text,
    grain text,
    period_year integer,
    period_month integer,
    coverage_status text,
    requested_month_count integer,
    covered_month_count integer,
    coverage_basis text,
    crash_count bigint,
    month_known_count bigint,
    excluded_unknown_month_count bigint,
    fatal_crash_count bigint,
    fatal_crash_known_count bigint,
    fatality_count bigint,
    fatality_known_count bigint,
    casualty_count bigint,
    casualty_known_count bigint
)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog
AS $d05$
DECLARE
    v_manifest jsonb;
    v_actual_kind text;
    v_status text;
    v_year_from integer;
    v_year_to integer;
    v_requested_months integer[];
BEGIN
    IF p_dataset_kind IS NULL
       OR p_dataset_kind NOT IN ('official', 'synthetic') THEN
        RAISE EXCEPTION 'D05_DATASET_KIND: expected official or synthetic'
            USING ERRCODE = '22023';
    END IF;
    IF p_grain IS NULL OR p_grain NOT IN ('year', 'month') THEN
        RAISE EXCEPTION 'D05_GRAIN: expected year or month'
            USING ERRCODE = '22023';
    END IF;

    SELECT candidate.dataset_kind, candidate.status, candidate.manifest
      INTO v_actual_kind, v_status, v_manifest
      FROM meta.batch AS candidate
     WHERE candidate.batch_id = p_batch_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'D05_BATCH: unknown batch'
            USING ERRCODE = '22023';
    END IF;
    IF v_actual_kind IS DISTINCT FROM p_dataset_kind THEN
        RAISE EXCEPTION 'D05_BATCH_MODE: batch belongs to another dataset kind'
            USING ERRCODE = '22023';
    END IF;
    IF v_status IS DISTINCT FROM 'succeeded' THEN
        RAISE EXCEPTION 'D05_BATCH_STATUS: batch is not succeeded'
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
        RAISE EXCEPTION 'D05_YEAR_RANGE: invalid year interval'
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
        RAISE EXCEPTION 'D05_MONTHS: use unique months from 1 to 12'
            USING ERRCODE = '22023';
    END IF;
    v_requested_months := COALESCE(
        p_months, ARRAY[1,2,3,4,5,6,7,8,9,10,11,12]
    );

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
        RAISE EXCEPTION 'D05_SOURCES: use unique non-empty source IDs'
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
        RAISE EXCEPTION 'D05_SOURCE: source is not enabled for this batch'
            USING ERRCODE = '22023';
    END IF;

    RETURN QUERY
    WITH selected_sources AS (
        SELECT source.source_id
          FROM dw.dim_source AS source
         WHERE source.batch_id = p_batch_id
           AND (p_source_ids IS NULL OR source.source_id = ANY(p_source_ids))
    ), requested_periods AS (
        SELECT
            source.source_id,
            requested_year.year::integer AS period_year,
            CASE WHEN p_grain = 'month' THEN requested_month.month END
                AS period_month
          FROM selected_sources AS source
         CROSS JOIN generate_series(v_year_from, v_year_to)
                    AS requested_year(year)
         CROSS JOIN LATERAL unnest(
            CASE WHEN p_grain = 'month'
                 THEN v_requested_months ELSE ARRAY[NULL::integer] END
         ) AS requested_month(month)
    ), crash_coverage AS (
        SELECT DISTINCT
            contract.value #>> '{content,input,source_id}' AS source_id,
            covered_year.year::integer AS covered_year,
            covered_month.month::integer AS covered_month,
            contract.value #>> '{content,identity,coverage,basis}' AS basis
          FROM jsonb_array_elements(
                   v_manifest #> '{rules,contracts}'
               ) AS contract(value)
         CROSS JOIN LATERAL generate_series(
            (contract.value #>> '{content,identity,coverage,year_from}')::integer,
            (contract.value #>> '{content,identity,coverage,year_to}')::integer
         ) AS covered_year(year)
         CROSS JOIN LATERAL jsonb_array_elements_text(
            contract.value #> '{content,identity,coverage,months}'
         ) AS covered_month(month)
         WHERE contract.value #>> '{content,input,entity_kind}' = 'crash'
    ), period_coverage AS (
        SELECT
            period.source_id,
            period.period_year,
            period.period_month,
            cardinality(
                CASE WHEN p_grain = 'month'
                     THEN ARRAY[period.period_month] ELSE v_requested_months END
            )::integer AS requested_month_count,
            count(DISTINCT coverage.covered_month)::integer AS covered_month_count,
            string_agg(DISTINCT coverage.basis, ' | ' ORDER BY coverage.basis)
                AS coverage_basis
          FROM requested_periods AS period
         LEFT JOIN crash_coverage AS coverage
           ON coverage.source_id = period.source_id
          AND coverage.covered_year = period.period_year
          AND coverage.covered_month = ANY(
                CASE WHEN p_grain = 'month'
                     THEN ARRAY[period.period_month] ELSE v_requested_months END
          )
         GROUP BY period.source_id, period.period_year, period.period_month
    ), aggregate_rows AS (
        SELECT
            period.*,
            count(fact.batch_id)::bigint AS crash_count,
            count(*) FILTER (WHERE fact.month_id IS NOT NULL)::bigint
                AS month_known_count,
            count(*) FILTER (
                WHERE fact.fatal_crash_eligible
                  AND fact.is_fatal_crash IS NOT NULL
            )::bigint AS fatal_crash_known_count,
            count(*) FILTER (
                WHERE fact.fatal_crash_eligible
                  AND fact.is_fatal_crash IS TRUE
            )::bigint AS fatal_crash_count,
            count(*) FILTER (
                WHERE fact.fatality_eligible
                  AND fact.fatality_count IS NOT NULL
            )::bigint AS fatality_known_count,
            sum(fact.fatality_count) FILTER (
                WHERE fact.fatality_eligible
                  AND fact.fatality_count IS NOT NULL
            )::bigint AS fatality_count,
            count(*) FILTER (
                WHERE fact.casualty_eligible
                  AND fact.casualty_count IS NOT NULL
            )::bigint AS casualty_known_count,
            sum(fact.casualty_count) FILTER (
                WHERE fact.casualty_eligible
                  AND fact.casualty_count IS NOT NULL
            )::bigint AS casualty_count
          FROM period_coverage AS period
         LEFT JOIN dw.fact_crash AS fact
           ON fact.batch_id = p_batch_id
          AND fact.source_id = period.source_id
          AND fact.occurrence_year = period.period_year
          AND (
              (p_grain = 'year' AND (
                  p_months IS NULL
                  OR (fact.month_id IS NOT NULL
                      AND (fact.month_id % 100) = ANY(p_months))
              ))
              OR
              (p_grain = 'month'
               AND fact.month_id = period.period_year * 100 + period.period_month)
          )
         GROUP BY period.source_id, period.period_year, period.period_month,
                  period.requested_month_count, period.covered_month_count,
                  period.coverage_basis
    )
    SELECT
        p_dataset_kind,
        p_batch_id,
        aggregate.source_id,
        p_grain,
        aggregate.period_year,
        aggregate.period_month,
        CASE
            WHEN aggregate.covered_month_count = 0 THEN 'not_covered'
            WHEN aggregate.covered_month_count = aggregate.requested_month_count
                THEN 'covered'
            ELSE 'partial'
        END,
        aggregate.requested_month_count,
        aggregate.covered_month_count,
        aggregate.coverage_basis,
        CASE WHEN aggregate.covered_month_count = 0
             THEN NULL ELSE aggregate.crash_count END,
        CASE WHEN aggregate.covered_month_count = 0
             THEN NULL ELSE aggregate.month_known_count END,
        CASE WHEN aggregate.covered_month_count = 0 THEN NULL
             WHEN p_grain = 'year' AND p_months IS NULL THEN 0
             ELSE (
                SELECT count(*)::bigint
                  FROM dw.fact_crash AS unknown_fact
                 WHERE unknown_fact.batch_id = p_batch_id
                   AND unknown_fact.source_id = aggregate.source_id
                   AND unknown_fact.occurrence_year = aggregate.period_year
                   AND unknown_fact.month_id IS NULL
             )
        END,
        CASE WHEN aggregate.covered_month_count = 0
                  OR aggregate.fatal_crash_known_count = 0
             THEN NULL ELSE aggregate.fatal_crash_count END,
        CASE WHEN aggregate.covered_month_count = 0
             THEN NULL ELSE aggregate.fatal_crash_known_count END,
        CASE WHEN aggregate.covered_month_count = 0
                  OR aggregate.fatality_known_count = 0
             THEN NULL ELSE aggregate.fatality_count END,
        CASE WHEN aggregate.covered_month_count = 0
             THEN NULL ELSE aggregate.fatality_known_count END,
        CASE WHEN aggregate.covered_month_count = 0
                  OR aggregate.casualty_known_count = 0
             THEN NULL ELSE aggregate.casualty_count END,
        CASE WHEN aggregate.covered_month_count = 0
             THEN NULL ELSE aggregate.casualty_known_count END
      FROM aggregate_rows AS aggregate
     ORDER BY aggregate.source_id, aggregate.period_year,
              aggregate.period_month NULLS FIRST;
END;
$d05$;

ALTER FUNCTION published.d05_trend(
    text, uuid, text, text[], integer, integer, integer[]
) OWNER TO arsia_migrator;

REVOKE ALL ON FUNCTION published.d05_trend(
    text, uuid, text, text[], integer, integer, integer[]
) FROM PUBLIC;
GRANT USAGE ON SCHEMA published TO arsia_loader;
GRANT EXECUTE ON FUNCTION published.d05_trend(
    text, uuid, text, text[], integer, integer, integer[]
) TO arsia_reader, arsia_loader;

COMMENT ON FUNCTION published.d05_trend(
    text, uuid, text, text[], integer, integer, integer[]
) IS 'D05 d05-0.1.0: fixed successful-batch L5 crash trend query.';
