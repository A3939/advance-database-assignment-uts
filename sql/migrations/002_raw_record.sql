BEGIN;

CREATE SCHEMA raw;

CREATE TABLE raw.record (
    raw_record_id uuid PRIMARY KEY,
    resource_id text NOT NULL,
    source_id text NOT NULL,
    file_sha256 text NOT NULL,
    parser_version text NOT NULL,
    row_locator text NOT NULL,
    payload jsonb NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT raw_identity_unique
        UNIQUE (resource_id, file_sha256, parser_version, row_locator) NOT DEFERRABLE,
    CONSTRAINT raw_record_source_unique
        UNIQUE (raw_record_id, source_id),
    CONSTRAINT raw_resource_source_fk
        FOREIGN KEY (resource_id, source_id)
        REFERENCES meta.resource (resource_id, source_id),
    CONSTRAINT raw_file_sha256_valid
        CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT raw_parser_locator_nonblank
        CHECK (btrim(parser_version) <> '' AND btrim(row_locator) <> ''),
    CONSTRAINT raw_payload_object
        CHECK (jsonb_typeof(payload) = 'object')
);

CREATE INDEX raw_file_idx
    ON raw.record USING btree (source_id, resource_id, file_sha256, parser_version);

COMMENT ON TABLE raw.record IS 'One immutable native row with its source-file lineage.';
COMMENT ON COLUMN raw.record.raw_record_id IS 'UUID supplied by the loader; repeated identity reuses the existing UUID.';
COMMENT ON COLUMN raw.record.resource_id IS 'Native resource that supplied this row.';
COMMENT ON COLUMN raw.record.source_id IS 'Source namespace matching the resource owner.';
COMMENT ON COLUMN raw.record.file_sha256 IS 'SHA256 of the original source file bytes.';
COMMENT ON COLUMN raw.record.parser_version IS 'Version of native extraction, without business transformation.';
COMMENT ON COLUMN raw.record.row_locator IS 'Stable original row location within the source file.';
COMMENT ON COLUMN raw.record.payload IS 'Complete native fields, retaining text, NULLs, and categories.';
COMMENT ON COLUMN raw.record.ingested_at IS 'Timestamp when this raw row was first inserted.';

COMMIT;