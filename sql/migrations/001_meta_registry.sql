BEGIN;

CREATE SCHEMA meta;

CREATE TABLE meta.source (
    source_id text PRIMARY KEY,
    jurisdiction_code text NOT NULL,
    source_name text NOT NULL,
    publisher text NOT NULL,
    CONSTRAINT source_id_nonblank CHECK (btrim(source_id) <> '')
);

CREATE TABLE meta.resource (
    resource_id text PRIMARY KEY,
    source_id text NOT NULL,
    resource_role text NOT NULL,
    entity_kind text NOT NULL,
    CONSTRAINT resource_source_pair_unique UNIQUE (resource_id, source_id),
    CONSTRAINT resource_source_fk
        FOREIGN KEY (source_id) REFERENCES meta.source (source_id),
    CONSTRAINT resource_entity_kind_valid
        CHECK (entity_kind IN ('crash', 'unit', 'person_raw', 'node_raw'))
);

COMMENT ON TABLE meta.source IS 'Current source registration; historical labels belong to a batch.';
COMMENT ON COLUMN meta.source.source_id IS 'Stable namespace; official and synthetic IDs differ.';
COMMENT ON COLUMN meta.source.jurisdiction_code IS 'Jurisdiction code, not restricted to three states.';
COMMENT ON COLUMN meta.source.source_name IS 'Currently registered source name.';
COMMENT ON COLUMN meta.source.publisher IS 'Publisher of this source.';

COMMENT ON TABLE meta.resource IS 'Logical resource owned by one source.';
COMMENT ON COLUMN meta.resource.resource_id IS 'Resource ID unique across the catalogue.';
COMMENT ON COLUMN meta.resource.source_id IS 'Owning source namespace.';
COMMENT ON COLUMN meta.resource.resource_role IS 'Configured role of this native resource.';
COMMENT ON COLUMN meta.resource.entity_kind IS 'Crash, unit, raw person, or raw node kind.';

COMMIT;
