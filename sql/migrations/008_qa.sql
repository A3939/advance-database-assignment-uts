BEGIN;

CREATE SCHEMA qa;

CREATE TABLE qa.check_result (
    batch_id uuid NOT NULL,
    rule_id text NOT NULL,
    object_key text NOT NULL,
    result text NOT NULL,
    affected_count bigint NOT NULL,
    actual jsonb NOT NULL,
    expected jsonb NOT NULL,
    evidence jsonb NOT NULL,
    raw_record_id uuid,
    checked_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT check_result_pkey
        PRIMARY KEY (batch_id, rule_id, object_key),
    CONSTRAINT check_result_batch_fk
        FOREIGN KEY (batch_id)
        REFERENCES meta.batch (batch_id),
    CONSTRAINT check_result_raw_record_fk
        FOREIGN KEY (raw_record_id)
        REFERENCES raw.record (raw_record_id),
    CONSTRAINT check_result_result_valid
        CHECK (result IN ('pass', 'limited', 'block')),
    CONSTRAINT check_result_affected_count_valid
        CHECK (affected_count >= 0),
    CONSTRAINT check_result_evidence_required
        CHECK (
            result = 'pass'
            OR evidence <> '{}'::jsonb
        )
);

CREATE INDEX qa_result_idx
    ON qa.check_result USING btree (
        batch_id,
        result,
        rule_id
    );

COMMENT ON TABLE qa.check_result IS
    'One rule-object quality result within a build batch.';
COMMENT ON COLUMN qa.check_result.batch_id IS
    'Build batch being checked.';
COMMENT ON COLUMN qa.check_result.rule_id IS
    'Readable identifier from the complete frozen rule set.';
COMMENT ON COLUMN qa.check_result.object_key IS
    'Identity of the checked batch, source, resource or row object.';
COMMENT ON COLUMN qa.check_result.result IS
    'Result state: pass, limited or block.';
COMMENT ON COLUMN qa.check_result.affected_count IS
    'Number of affected rows or objects.';
COMMENT ON COLUMN qa.check_result.actual IS
    'Measured values, ranges or states.';
COMMENT ON COLUMN qa.check_result.expected IS
    'Expectations frozen for this batch.';
COMMENT ON COLUMN qa.check_result.evidence IS
    'Evidence, definitions, reasons and source locators.';
COMMENT ON COLUMN qa.check_result.raw_record_id IS
    'Primary affected raw row when applicable.';
COMMENT ON COLUMN qa.check_result.checked_at IS
    'UTC-aware time when this check was executed.';

COMMIT;
