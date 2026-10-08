"""Additive, hash-checked migrations for the existing local database."""
import hashlib

MIGRATIONS = [(1, """
CREATE TABLE source_versions (
 id text PRIMARY KEY, source_id text NOT NULL, contract jsonb NOT NULL,
 contract_sha256 text NOT NULL, admission jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(source_id,contract_sha256)
);
CREATE TABLE adapter_versions (
 id text PRIMARY KEY, source_version_id text NOT NULL REFERENCES source_versions(id),
 source_id text NOT NULL, code_sha256 text NOT NULL, code_path text NOT NULL,
 dependency_version jsonb NOT NULL, structure_signature jsonb NOT NULL,
 verification jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX adapter_source ON adapter_versions(source_id,created_at DESC);
CREATE TABLE agent_sessions (
 id uuid PRIMARY KEY, job_id uuid NOT NULL UNIQUE REFERENCES jobs(id),
 status text NOT NULL, checkpoint jsonb NOT NULL DEFAULT '{}',
 model_calls integer NOT NULL DEFAULT 0, tool_calls integer NOT NULL DEFAULT 0,
 correction_count integer NOT NULL DEFAULT 0, compute_seconds numeric NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE agent_steps (
 id bigserial PRIMARY KEY, session_id uuid NOT NULL REFERENCES agent_sessions(id),
 attempt_id uuid NOT NULL REFERENCES attempts(id), kind text NOT NULL,
 name text NOT NULL, status text NOT NULL, arguments jsonb NOT NULL DEFAULT '{}',
 result jsonb, evidence_path text, created_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz
);
CREATE TABLE canonical_casualty (
 batch_id uuid NOT NULL REFERENCES batches(id), record_id text NOT NULL,
 crash_id text, unit_id text, payload jsonb NOT NULL, PRIMARY KEY(batch_id,record_id)
);
CREATE TABLE canonical_observation (
 batch_id uuid NOT NULL REFERENCES batches(id), record_id text NOT NULL,
 year integer, month integer, payload jsonb NOT NULL, PRIMARY KEY(batch_id,record_id)
);
ALTER TABLE batches ADD COLUMN source_version_id text REFERENCES source_versions(id);
ALTER TABLE batches ADD COLUMN adapter_version_id text REFERENCES adapter_versions(id);
ALTER TABLE batches ADD COLUMN update_mode text NOT NULL DEFAULT 'snapshot';
ALTER TABLE batches ADD COLUMN base_batch_id uuid REFERENCES batches(id);
"""), (2, """
ALTER TABLE batches ADD COLUMN candidate_fingerprint text;
CREATE INDEX batch_candidate ON batches(source_id,candidate_fingerprint);
CREATE INDEX canonical_unit_identity ON canonical_unit(batch_id,(payload->>'canonical_id'));
CREATE INDEX canonical_casualty_crash ON canonical_casualty(batch_id,crash_id);
CREATE INDEX observations_analysis ON canonical_observation(batch_id,year,month);
"""), (3, """
CREATE TABLE source_identities (
 identity_key text PRIMARY KEY, source_id text NOT NULL,
 first_source_version_id text NOT NULL REFERENCES source_versions(id),
 identity jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX source_identity_source ON source_identities(source_id);
""")]


def migrate(conn):
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(731982703)")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version integer PRIMARY KEY,sha256 text NOT NULL,applied_at timestamptz NOT NULL DEFAULT now())")
        for version, statement in MIGRATIONS:
            digest = hashlib.sha256(statement.encode()).hexdigest()
            row = conn.execute("SELECT sha256 FROM schema_migrations WHERE version=%s", (version,)).fetchone()
            if row:
                if row["sha256"] != digest:
                    raise RuntimeError("Applied migration hash changed; refusing automatic modification")
                continue
            conn.execute(statement)
            conn.execute("INSERT INTO schema_migrations(version,sha256) VALUES(%s,%s)", (version, digest))
