BEGIN;

CREATE SCHEMA dw;

CREATE TABLE dw.dim_source (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    source_name text NOT NULL,
    jurisdiction_code text NOT NULL,
    release_label text NOT NULL,
    release_scope text NOT NULL,

    CONSTRAINT dim_source_pkey
        PRIMARY KEY (batch_id, source_id),
    CONSTRAINT dim_source_batch_fk
        FOREIGN KEY (batch_id)
        REFERENCES meta.batch (batch_id),
    CONSTRAINT dim_source_source_fk
        FOREIGN KEY (source_id)
        REFERENCES meta.source (source_id)
);

CREATE TABLE dw.dim_month (
    month_id integer NOT NULL,
    calendar_year integer NOT NULL,
    calendar_month integer NOT NULL,

    CONSTRAINT dim_month_pkey
        PRIMARY KEY (month_id),
    CONSTRAINT dim_month_year_month_unique
        UNIQUE (calendar_year, calendar_month),
    CONSTRAINT dim_month_calendar_month_valid
        CHECK (calendar_month BETWEEN 1 AND 12),
    CONSTRAINT dim_month_id_consistent
        CHECK (month_id = ((calendar_year * 100) + calendar_month))
);

CREATE TABLE dw.dim_severity (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    severity_code text NOT NULL,
    severity_label text NOT NULL,
    definition_version text NOT NULL,
    definition_text text NOT NULL,

    CONSTRAINT dim_severity_pkey
        PRIMARY KEY (batch_id, source_id, severity_code),
    CONSTRAINT dim_severity_source_fk
        FOREIGN KEY (batch_id, source_id)
        REFERENCES dw.dim_source (batch_id, source_id)
);

CREATE TABLE dw.fact_crash (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    crash_key text NOT NULL,
    occurrence_year integer NOT NULL,
    month_id integer,
    severity_code text NOT NULL,
    is_fatal_crash boolean,
    fatality_count integer,
    casualty_count integer,
    fatal_crash_eligible boolean NOT NULL,
    fatality_eligible boolean NOT NULL,
    casualty_eligible boolean NOT NULL,
    latitude numeric(10, 7),
    longitude numeric(10, 7),
    map_eligible boolean NOT NULL,

    CONSTRAINT fact_crash_pkey
        PRIMARY KEY (
            batch_id,
            source_id,
            release_scope,
            crash_key
        ),
    CONSTRAINT fact_crash_canonical_fk
        FOREIGN KEY (
            batch_id,
            source_id,
            release_scope,
            crash_key
        )
        REFERENCES canonical.crash (
            batch_id,
            source_id,
            release_scope,
            crash_key
        ),
    CONSTRAINT fact_crash_source_fk
        FOREIGN KEY (batch_id, source_id)
        REFERENCES dw.dim_source (batch_id, source_id),
    CONSTRAINT fact_crash_severity_fk
        FOREIGN KEY (batch_id, source_id, severity_code)
        REFERENCES dw.dim_severity (
            batch_id,
            source_id,
            severity_code
        ),
    CONSTRAINT fact_crash_month_fk
        FOREIGN KEY (month_id)
        REFERENCES dw.dim_month (month_id),
    CONSTRAINT fact_crash_month_year_consistent
        CHECK (
            month_id IS NULL
            OR (month_id / 100) = occurrence_year
        ),
    CONSTRAINT fact_crash_fatality_count_valid
        CHECK (
            fatality_count IS NULL
            OR fatality_count >= 0
        ),
    CONSTRAINT fact_crash_casualty_count_valid
        CHECK (
            casualty_count IS NULL
            OR casualty_count >= 0
        ),
    CONSTRAINT fact_crash_fatal_eligibility_valid
        CHECK (
            NOT fatal_crash_eligible
            OR is_fatal_crash IS NOT NULL
        ),
    CONSTRAINT fact_crash_fatality_eligibility_valid
        CHECK (
            NOT fatality_eligible
            OR fatality_count IS NOT NULL
        ),
    CONSTRAINT fact_crash_casualty_eligibility_valid
        CHECK (
            NOT casualty_eligible
            OR casualty_count IS NOT NULL
        ),
    CONSTRAINT fact_crash_map_eligibility_valid
        CHECK (
            NOT map_eligible
            OR (
                latitude IS NOT NULL
                AND longitude IS NOT NULL
            )
        )
);

CREATE INDEX fact_trend_idx
    ON dw.fact_crash USING btree (
        batch_id,
        source_id,
        occurrence_year,
        month_id
    );

COMMENT ON TABLE dw.dim_source IS
    'One frozen display dimension row per source and batch.';
COMMENT ON COLUMN dw.dim_source.batch_id IS
    'Frozen snapshot version.';
COMMENT ON COLUMN dw.dim_source.source_id IS
    'Source namespace.';
COMMENT ON COLUMN dw.dim_source.source_name IS
    'Source name frozen from the batch manifest.';
COMMENT ON COLUMN dw.dim_source.jurisdiction_code IS
    'Jurisdiction frozen from the batch manifest.';
COMMENT ON COLUMN dw.dim_source.release_label IS
    'Recorded source release label, not ingestion time.';
COMMENT ON COLUMN dw.dim_source.release_scope IS
    'Release identity scope used by this batch.';

COMMENT ON TABLE dw.dim_month IS
    'One Gregorian calendar year-month shared across batches.';
COMMENT ON COLUMN dw.dim_month.month_id IS
    'Integer YYYYMM key.';
COMMENT ON COLUMN dw.dim_month.calendar_year IS
    'Gregorian calendar year.';
COMMENT ON COLUMN dw.dim_month.calendar_month IS
    'Gregorian calendar month from 1 through 12.';

COMMENT ON TABLE dw.dim_severity IS
    'One source-specific severity category per batch.';
COMMENT ON COLUMN dw.dim_severity.batch_id IS
    'Snapshot version freezing the definition.';
COMMENT ON COLUMN dw.dim_severity.source_id IS
    'Owning source namespace.';
COMMENT ON COLUMN dw.dim_severity.severity_code IS
    'Source-specific category or explicit missing code.';
COMMENT ON COLUMN dw.dim_severity.severity_label IS
    'Display label for this category version.';
COMMENT ON COLUMN dw.dim_severity.definition_version IS
    'Verified or restricted source-definition version.';
COMMENT ON COLUMN dw.dim_severity.definition_text IS
    'Frozen definition, comparability and missingness notes.';

COMMENT ON TABLE dw.fact_crash IS
    'One analytical fact per crash and complete batch snapshot.';
COMMENT ON COLUMN dw.fact_crash.batch_id IS
    'Complete snapshot version fixed for report queries.';
COMMENT ON COLUMN dw.fact_crash.source_id IS
    'Source namespace and dimension-key component.';
COMMENT ON COLUMN dw.fact_crash.release_scope IS
    'Source crash identity scope.';
COMMENT ON COLUMN dw.fact_crash.crash_key IS
    'Complete crash business key.';
COMMENT ON COLUMN dw.fact_crash.occurrence_year IS
    'Crash occurrence year.';
COMMENT ON COLUMN dw.fact_crash.month_id IS
    'Trusted YYYYMM key, or NULL for year-only crashes.';
COMMENT ON COLUMN dw.fact_crash.severity_code IS
    'Source-specific severity dimension code.';
COMMENT ON COLUMN dw.fact_crash.is_fatal_crash IS
    'Fatal-crash determination copied from Canonical.';
COMMENT ON COLUMN dw.fact_crash.fatality_count IS
    'Fatality count copied from Canonical.';
COMMENT ON COLUMN dw.fact_crash.casualty_count IS
    'Casualty count copied from Canonical.';
COMMENT ON COLUMN dw.fact_crash.fatal_crash_eligible IS
    'Eligibility for the fatal-crash metric.';
COMMENT ON COLUMN dw.fact_crash.fatality_eligible IS
    'Eligibility for the fatality-count metric.';
COMMENT ON COLUMN dw.fact_crash.casualty_eligible IS
    'Eligibility for the casualty-count metric.';
COMMENT ON COLUMN dw.fact_crash.latitude IS
    'Trusted latitude copied from Canonical.';
COMMENT ON COLUMN dw.fact_crash.longitude IS
    'Trusted longitude copied from Canonical.';
COMMENT ON COLUMN dw.fact_crash.map_eligible IS
    'Whether this crash may appear in the selected map product.';

COMMIT;
