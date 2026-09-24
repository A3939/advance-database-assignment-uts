BEGIN;

CREATE SCHEMA canonical;

CREATE TABLE canonical.crash (
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
    fatal_crash_eligible boolean NOT NULL DEFAULT false,
    fatality_eligible boolean NOT NULL DEFAULT false,
    casualty_eligible boolean NOT NULL DEFAULT false,
    latitude numeric(10, 7),
    longitude numeric(10, 7),
    location_crs text,
    map_eligible boolean NOT NULL DEFAULT false,
    location_record_id uuid,
    quality_notes jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT canonical_crash_pkey
        PRIMARY KEY (
            batch_id,
            source_id,
            release_scope,
            crash_key
        ),
    CONSTRAINT canonical_crash_satellite_fk
        FOREIGN KEY (
            batch_id,
            source_id,
            release_scope,
            crash_key
        )
        REFERENCES rv.sat_crash (
            batch_id,
            source_id,
            release_scope,
            crash_key
        ),
    CONSTRAINT canonical_crash_raw_record_fk
        FOREIGN KEY (raw_record_id, source_id)
        REFERENCES raw.record (raw_record_id, source_id),
    CONSTRAINT canonical_crash_location_record_fk
        FOREIGN KEY (location_record_id, source_id)
        REFERENCES raw.record (raw_record_id, source_id),
    CONSTRAINT canonical_crash_occurrence_year_valid
        CHECK (occurrence_year BETWEEN 1900 AND 2100),
    CONSTRAINT canonical_crash_occurrence_month_valid
        CHECK (
            occurrence_month IS NULL
            OR occurrence_month BETWEEN 1 AND 12
        ),
    CONSTRAINT canonical_crash_date_precision_valid
        CHECK (date_precision IN ('year', 'month', 'day')),
    CONSTRAINT canonical_crash_date_precision_consistent
        CHECK (
            (
                date_precision = 'year'
                AND occurrence_month IS NULL
                AND occurrence_date IS NULL
            )
            OR
            (
                date_precision = 'month'
                AND occurrence_month IS NOT NULL
                AND occurrence_date IS NULL
            )
            OR
            (
                date_precision = 'day'
                AND occurrence_month IS NOT NULL
                AND occurrence_date IS NOT NULL
                AND EXTRACT(YEAR FROM occurrence_date) = occurrence_year
                AND EXTRACT(MONTH FROM occurrence_date) = occurrence_month
            )
        ),
    CONSTRAINT canonical_crash_fatality_count_valid
        CHECK (
            fatality_count IS NULL
            OR fatality_count >= 0
        ),
    CONSTRAINT canonical_crash_casualty_count_valid
        CHECK (
            casualty_count IS NULL
            OR casualty_count >= 0
        ),
    CONSTRAINT canonical_crash_fatal_eligibility_valid
        CHECK (
            NOT fatal_crash_eligible
            OR is_fatal_crash IS NOT NULL
        ),
    CONSTRAINT canonical_crash_fatality_eligibility_valid
        CHECK (
            NOT fatality_eligible
            OR fatality_count IS NOT NULL
        ),
    CONSTRAINT canonical_crash_casualty_eligibility_valid
        CHECK (
            NOT casualty_eligible
            OR casualty_count IS NOT NULL
        ),
    CONSTRAINT canonical_crash_coordinates_paired
        CHECK (
            (latitude IS NULL) = (longitude IS NULL)
        ),
    CONSTRAINT canonical_crash_latitude_valid
        CHECK (
            latitude IS NULL
            OR latitude BETWEEN -90 AND 90
        ),
    CONSTRAINT canonical_crash_longitude_valid
        CHECK (
            longitude IS NULL
            OR longitude BETWEEN -180 AND 180
        ),
    CONSTRAINT canonical_crash_map_eligibility_valid
        CHECK (
            NOT map_eligible
            OR (
                latitude IS NOT NULL
                AND longitude IS NOT NULL
                AND location_crs = 'EPSG:4326'
                AND location_record_id IS NOT NULL
            )
        ),
    CONSTRAINT canonical_crash_quality_notes_object
        CHECK (jsonb_typeof(quality_notes) = 'object')
);

CREATE INDEX crash_year_idx
    ON canonical.crash USING btree (
        batch_id,
        source_id,
        occurrence_year
    );

CREATE TABLE canonical.unit (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    unit_key text NOT NULL,
    crash_key text NOT NULL,
    raw_record_id uuid NOT NULL,
    unit_type_raw text,
    unit_type_code text,
    statistical_scope text NOT NULL,
    count_eligible boolean NOT NULL DEFAULT false,
    quality_notes jsonb NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT canonical_unit_pkey
        PRIMARY KEY (
            batch_id,
            source_id,
            release_scope,
            unit_key
        ),
    CONSTRAINT canonical_unit_link_fk
        FOREIGN KEY (
            batch_id,
            source_id,
            release_scope,
            unit_key,
            crash_key
        )
        REFERENCES rv.link_crash_unit (
            batch_id,
            source_id,
            release_scope,
            unit_key,
            crash_key
        ),
    CONSTRAINT canonical_unit_crash_fk
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
    CONSTRAINT canonical_unit_raw_record_fk
        FOREIGN KEY (raw_record_id, source_id)
        REFERENCES raw.record (raw_record_id, source_id),
    CONSTRAINT canonical_unit_statistical_scope_nonblank
        CHECK (btrim(statistical_scope) <> ''),
    CONSTRAINT canonical_unit_count_eligibility_valid
        CHECK (
            NOT count_eligible
            OR unit_type_code IS NOT NULL
        ),
    CONSTRAINT canonical_unit_quality_notes_object
        CHECK (jsonb_typeof(quality_notes) = 'object')
);

CREATE INDEX unit_parent_idx
    ON canonical.unit USING btree (
        batch_id,
        source_id,
        release_scope,
        crash_key
    );

COMMENT ON TABLE canonical.crash IS
    'One typed crash per source release scope and complete batch snapshot.';
COMMENT ON COLUMN canonical.crash.batch_id IS
    'Complete snapshot version.';
COMMENT ON COLUMN canonical.crash.source_id IS
    'Source namespace.';
COMMENT ON COLUMN canonical.crash.release_scope IS
    'Source release identity scope.';
COMMENT ON COLUMN canonical.crash.crash_key IS
    'Complete crash business key.';
COMMENT ON COLUMN canonical.crash.raw_record_id IS
    'Primary crash raw-row lineage.';
COMMENT ON COLUMN canonical.crash.occurrence_year IS
    'Crash occurrence year, never report year.';
COMMENT ON COLUMN canonical.crash.occurrence_month IS
    'Evidence-supported month, or NULL when unknown.';
COMMENT ON COLUMN canonical.crash.occurrence_date IS
    'Actual crash date only when day precision is known.';
COMMENT ON COLUMN canonical.crash.date_precision IS
    'Available date precision: year, month or day.';
COMMENT ON COLUMN canonical.crash.severity_raw IS
    'Native severity text or code.';
COMMENT ON COLUMN canonical.crash.severity_code IS
    'Source-specific mapped severity code.';
COMMENT ON COLUMN canonical.crash.severity_definition_version IS
    'Frozen source severity-definition version.';
COMMENT ON COLUMN canonical.crash.is_fatal_crash IS
    'Fatal-crash determination, or NULL when unknown.';
COMMENT ON COLUMN canonical.crash.fatality_count IS
    'Number of fatalities, or NULL when unknown.';
COMMENT ON COLUMN canonical.crash.casualty_count IS
    'Confirmed casualty count, or NULL when unknown.';
COMMENT ON COLUMN canonical.crash.fatal_crash_eligible IS
    'Whether this row contributes to fatal-crash metrics.';
COMMENT ON COLUMN canonical.crash.fatality_eligible IS
    'Whether fatality_count may be aggregated.';
COMMENT ON COLUMN canonical.crash.casualty_eligible IS
    'Whether casualty_count may be aggregated.';
COMMENT ON COLUMN canonical.crash.latitude IS
    'Confirmed WGS84 latitude.';
COMMENT ON COLUMN canonical.crash.longitude IS
    'Confirmed WGS84 longitude.';
COMMENT ON COLUMN canonical.crash.location_crs IS
    'Coordinate reference system for the location.';
COMMENT ON COLUMN canonical.crash.map_eligible IS
    'Whether this location may appear in phase-one maps.';
COMMENT ON COLUMN canonical.crash.location_record_id IS
    'Trusted crash or node raw-row location lineage.';
COMMENT ON COLUMN canonical.crash.quality_notes IS
    'JSON evidence for missingness, eligibility and location matching.';

COMMENT ON TABLE canonical.unit IS
    'One typed real-unit detail per batch under its source definition.';
COMMENT ON COLUMN canonical.unit.batch_id IS
    'Complete snapshot version.';
COMMENT ON COLUMN canonical.unit.source_id IS
    'Source namespace.';
COMMENT ON COLUMN canonical.unit.release_scope IS
    'Source release identity scope.';
COMMENT ON COLUMN canonical.unit.unit_key IS
    'Complete unit key including parent-crash components.';
COMMENT ON COLUMN canonical.unit.crash_key IS
    'Parent crash in the same batch, source and release scope.';
COMMENT ON COLUMN canonical.unit.raw_record_id IS
    'Real-unit raw-row lineage.';
COMMENT ON COLUMN canonical.unit.unit_type_raw IS
    'Native unit type retained when available.';
COMMENT ON COLUMN canonical.unit.unit_type_code IS
    'Source-specific analytical unit type code.';
COMMENT ON COLUMN canonical.unit.statistical_scope IS
    'Source-defined unit-counting scope.';
COMMENT ON COLUMN canonical.unit.count_eligible IS
    'Whether this unit contributes to source-specific counts.';
COMMENT ON COLUMN canonical.unit.quality_notes IS
    'JSON evidence for classification and relationship decisions.';

COMMIT;
