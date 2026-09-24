-- C03 C-to-A temporary projection contracts.
-- These tables exist only in B's shared PostgreSQL session.

DROP TABLE IF EXISTS pg_temp.arsia_i_crash;
DROP TABLE IF EXISTS pg_temp.arsia_i_unit;

CREATE TEMP TABLE arsia_i_crash (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    crash_key text NOT NULL,
    raw_record_id uuid NOT NULL,
    occurrence_year integer NOT NULL,
    occurrence_month integer,
    occurrence_date date,
    date_precision text NOT NULL,
    severity_raw text,
    severity_code text NOT NULL,
    severity_definition_version text NOT NULL,
    is_fatal_crash boolean,
    fatality_count integer,
    casualty_count integer,
    fatal_crash_eligible boolean NOT NULL,
    fatality_eligible boolean NOT NULL,
    casualty_eligible boolean NOT NULL,
    latitude numeric(10,7),
    longitude numeric(10,7),
    location_crs text,
    map_eligible boolean NOT NULL,
    location_record_id uuid,
    quality_notes jsonb NOT NULL
);

CREATE TEMP TABLE arsia_i_unit (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    unit_key text NOT NULL,
    crash_key text NOT NULL,
    raw_record_id uuid NOT NULL,
    unit_type_raw text,
    unit_type_code text,
    statistical_scope text NOT NULL,
    count_eligible boolean NOT NULL,
    quality_notes jsonb NOT NULL
);
