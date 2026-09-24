BEGIN;

CREATE TABLE meta.batch (
    batch_id uuid PRIMARY KEY,
    dataset_kind text NOT NULL,
    input_fingerprint text NOT NULL,
    manifest jsonb NOT NULL,
    status text NOT NULL DEFAULT 'running',
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error_details jsonb,

    CONSTRAINT batch_identity_status_unique
        UNIQUE (batch_id, dataset_kind, status),
    CONSTRAINT batch_dataset_kind_valid
        CHECK (dataset_kind IN ('official', 'synthetic')),
    CONSTRAINT batch_fingerprint_valid
        CHECK (input_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT batch_manifest_object
        CHECK (jsonb_typeof(manifest) = 'object'),
    CONSTRAINT batch_status_valid
        CHECK (status IN ('running', 'succeeded', 'failed')),
    CONSTRAINT batch_status_timing_valid
        CHECK (
            (status = 'running' AND finished_at IS NULL)
            OR
            (status <> 'running' AND finished_at IS NOT NULL)
        ),
    CONSTRAINT batch_failed_error_required
        CHECK (status <> 'failed' OR error_details IS NOT NULL)
);

CREATE INDEX batch_fingerprint_idx
    ON meta.batch USING btree
    (dataset_kind, input_fingerprint, status);

CREATE TABLE meta.current_release (
    dataset_kind text PRIMARY KEY,
    batch_id uuid NOT NULL,
    batch_status text NOT NULL DEFAULT 'succeeded',
    switched_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT current_release_batch_fk
        FOREIGN KEY (batch_id, dataset_kind, batch_status)
        REFERENCES meta.batch (batch_id, dataset_kind, status),
    CONSTRAINT current_release_dataset_kind_valid
        CHECK (dataset_kind IN ('official', 'synthetic')),
    CONSTRAINT current_release_succeeded_only
        CHECK (batch_status = 'succeeded')
);

COMMENT ON TABLE meta.batch IS
    'One attempt to build a complete snapshot of all enabled sources.';
COMMENT ON COLUMN meta.batch.batch_id IS
    'UUID identifying one build attempt; failed retries use a new UUID.';
COMMENT ON COLUMN meta.batch.dataset_kind IS
    'Official or synthetic query space.';
COMMENT ON COLUMN meta.batch.input_fingerprint IS
    'SHA256 of the frozen complete build input contract.';
COMMENT ON COLUMN meta.batch.manifest IS
    'Immutable frozen sources, files, rules, analysis and required checks.';
COMMENT ON COLUMN meta.batch.status IS
    'Build state: running, succeeded or failed.';
COMMENT ON COLUMN meta.batch.started_at IS
    'Time when this build attempt was registered.';
COMMENT ON COLUMN meta.batch.finished_at IS
    'Time when a successful or failed build completed.';
COMMENT ON COLUMN meta.batch.error_details IS
    'Failure details retained after a failed build rollback.';

COMMENT ON TABLE meta.current_release IS
    'Current successful complete-snapshot pointer for each dataset kind.';
COMMENT ON COLUMN meta.current_release.dataset_kind IS
    'Official or synthetic query space.';
COMMENT ON COLUMN meta.current_release.batch_id IS
    'Current successful batch for this dataset kind.';
COMMENT ON COLUMN meta.current_release.batch_status IS
    'Fixed succeeded status used by the composite foreign key.';
COMMENT ON COLUMN meta.current_release.switched_at IS
    'Time when the current pointer changed.';

COMMIT;
