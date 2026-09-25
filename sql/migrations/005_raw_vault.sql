BEGIN;

CREATE SCHEMA rv;

CREATE TABLE rv.hub_crash (
    source_id text NOT NULL,
    release_scope text NOT NULL,
    crash_key text NOT NULL,
    first_seen_batch_id uuid NOT NULL,

    CONSTRAINT hub_crash_pkey
        PRIMARY KEY (source_id, release_scope, crash_key),
    CONSTRAINT hub_crash_source_fk
        FOREIGN KEY (source_id)
        REFERENCES meta.source (source_id),
    CONSTRAINT hub_crash_first_seen_batch_fk
        FOREIGN KEY (first_seen_batch_id)
        REFERENCES meta.batch (batch_id),
    CONSTRAINT hub_crash_key_nonblank
        CHECK (
            btrim(release_scope) <> ''
            AND btrim(crash_key) <> ''
        )
);

CREATE TABLE rv.hub_unit (
    source_id text NOT NULL,
    release_scope text NOT NULL,
    unit_key text NOT NULL,
    first_seen_batch_id uuid NOT NULL,

    CONSTRAINT hub_unit_pkey
        PRIMARY KEY (source_id, release_scope, unit_key),
    CONSTRAINT hub_unit_source_fk
        FOREIGN KEY (source_id)
        REFERENCES meta.source (source_id),
    CONSTRAINT hub_unit_first_seen_batch_fk
        FOREIGN KEY (first_seen_batch_id)
        REFERENCES meta.batch (batch_id),
    CONSTRAINT hub_unit_key_nonblank
        CHECK (
            btrim(release_scope) <> ''
            AND btrim(unit_key) <> ''
        )
);

CREATE TABLE rv.sat_crash (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    crash_key text NOT NULL,
    raw_record_id uuid NOT NULL,
    attributes jsonb NOT NULL,

    CONSTRAINT sat_crash_pkey
        PRIMARY KEY (
            batch_id,
            source_id,
            release_scope,
            crash_key
        ),
    CONSTRAINT sat_crash_batch_fk
        FOREIGN KEY (batch_id)
        REFERENCES meta.batch (batch_id),
    CONSTRAINT sat_crash_hub_fk
        FOREIGN KEY (source_id, release_scope, crash_key)
        REFERENCES rv.hub_crash (
            source_id,
            release_scope,
            crash_key
        ),
    CONSTRAINT sat_crash_raw_record_fk
        FOREIGN KEY (raw_record_id, source_id)
        REFERENCES raw.record (raw_record_id, source_id),
    CONSTRAINT sat_crash_attributes_object
        CHECK (jsonb_typeof(attributes) = 'object')
);

CREATE TABLE rv.sat_unit (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    unit_key text NOT NULL,
    raw_record_id uuid NOT NULL,
    attributes jsonb NOT NULL,

    CONSTRAINT sat_unit_pkey
        PRIMARY KEY (
            batch_id,
            source_id,
            release_scope,
            unit_key
        ),
    CONSTRAINT sat_unit_batch_fk
        FOREIGN KEY (batch_id)
        REFERENCES meta.batch (batch_id),
    CONSTRAINT sat_unit_hub_fk
        FOREIGN KEY (source_id, release_scope, unit_key)
        REFERENCES rv.hub_unit (
            source_id,
            release_scope,
            unit_key
        ),
    CONSTRAINT sat_unit_raw_record_fk
        FOREIGN KEY (raw_record_id, source_id)
        REFERENCES raw.record (raw_record_id, source_id),
    CONSTRAINT sat_unit_attributes_object
        CHECK (jsonb_typeof(attributes) = 'object')
);

CREATE TABLE rv.link_crash_unit (
    batch_id uuid NOT NULL,
    source_id text NOT NULL,
    release_scope text NOT NULL,
    unit_key text NOT NULL,
    crash_key text NOT NULL,

    CONSTRAINT link_crash_unit_pkey
        PRIMARY KEY (
            batch_id,
            source_id,
            release_scope,
            unit_key
        ),
    CONSTRAINT link_crash_unit_complete_unique
        UNIQUE (
            batch_id,
            source_id,
            release_scope,
            unit_key,
            crash_key
        ),
    CONSTRAINT link_crash_unit_crash_fk
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
    CONSTRAINT link_crash_unit_unit_fk
        FOREIGN KEY (
            batch_id,
            source_id,
            release_scope,
            unit_key
        )
        REFERENCES rv.sat_unit (
            batch_id,
            source_id,
            release_scope,
            unit_key
        )
);

CREATE INDEX link_parent_idx
    ON rv.link_crash_unit USING btree (
        batch_id,
        source_id,
        release_scope,
        crash_key
    );

COMMENT ON TABLE rv.hub_crash IS
    'One complete crash business key within a source release scope.';
COMMENT ON COLUMN rv.hub_crash.source_id IS
    'Source namespace.';
COMMENT ON COLUMN rv.hub_crash.release_scope IS
    'Release scope in which this identity is valid.';
COMMENT ON COLUMN rv.hub_crash.crash_key IS
    'Canonical JSON-array text containing the complete crash key.';
COMMENT ON COLUMN rv.hub_crash.first_seen_batch_id IS
    'First build batch that referenced this crash identity.';

COMMENT ON TABLE rv.hub_unit IS
    'One complete real-unit business key within a source release scope.';
COMMENT ON COLUMN rv.hub_unit.source_id IS
    'Source namespace.';
COMMENT ON COLUMN rv.hub_unit.release_scope IS
    'Release scope in which this identity is valid.';
COMMENT ON COLUMN rv.hub_unit.unit_key IS
    'Canonical JSON-array text containing the complete real-unit key.';
COMMENT ON COLUMN rv.hub_unit.first_seen_batch_id IS
    'First build batch that referenced this unit identity.';

COMMENT ON TABLE rv.sat_crash IS
    'One selected structured crash projection for each batch.';
COMMENT ON COLUMN rv.sat_crash.batch_id IS
    'Complete snapshot build version.';
COMMENT ON COLUMN rv.sat_crash.source_id IS
    'Source namespace shared with the Hub and raw record.';
COMMENT ON COLUMN rv.sat_crash.release_scope IS
    'Source release identity scope.';
COMMENT ON COLUMN rv.sat_crash.crash_key IS
    'Complete crash business key.';
COMMENT ON COLUMN rv.sat_crash.raw_record_id IS
    'Selected primary crash raw row.';
COMMENT ON COLUMN rv.sat_crash.attributes IS
    'Structured crash projection and supporting evidence for this batch.';

COMMENT ON TABLE rv.sat_unit IS
    'One structured projection snapshot of a real unit per batch.';
COMMENT ON COLUMN rv.sat_unit.batch_id IS
    'Complete snapshot build version.';
COMMENT ON COLUMN rv.sat_unit.source_id IS
    'Source namespace shared with the Hub and raw record.';
COMMENT ON COLUMN rv.sat_unit.release_scope IS
    'Source release identity scope.';
COMMENT ON COLUMN rv.sat_unit.unit_key IS
    'Complete real-unit business key.';
COMMENT ON COLUMN rv.sat_unit.raw_record_id IS
    'Selected real-unit raw row.';
COMMENT ON COLUMN rv.sat_unit.attributes IS
    'Structured unit projection and supporting evidence for this batch.';

COMMENT ON TABLE rv.link_crash_unit IS
    'Exactly one parent crash relationship per real unit per batch.';
COMMENT ON COLUMN rv.link_crash_unit.batch_id IS
    'Relationship snapshot version.';
COMMENT ON COLUMN rv.link_crash_unit.source_id IS
    'Shared source namespace.';
COMMENT ON COLUMN rv.link_crash_unit.release_scope IS
    'Shared release identity scope.';
COMMENT ON COLUMN rv.link_crash_unit.unit_key IS
    'Complete real-unit business key.';
COMMENT ON COLUMN rv.link_crash_unit.crash_key IS
    'Complete parent crash business key.';

COMMIT;