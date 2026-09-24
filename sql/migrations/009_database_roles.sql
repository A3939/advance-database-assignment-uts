BEGIN;

CREATE ROLE arsia_migrator
    NOLOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION;

CREATE ROLE arsia_reader
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION;

GRANT arsia_migrator TO arsia_owner WITH ADMIN OPTION;

REVOKE CONNECT ON DATABASE arsia FROM PUBLIC;
GRANT CONNECT ON DATABASE arsia
    TO arsia_owner, arsia_loader, arsia_reader;
GRANT CREATE ON DATABASE arsia TO arsia_migrator;

REVOKE ALL ON SCHEMA meta, raw, rv, canonical, dw, qa FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA meta, raw, rv, canonical, dw, qa
    FROM PUBLIC;

ALTER SCHEMA meta OWNER TO arsia_migrator;
ALTER SCHEMA raw OWNER TO arsia_migrator;
ALTER SCHEMA rv OWNER TO arsia_migrator;
ALTER SCHEMA canonical OWNER TO arsia_migrator;
ALTER SCHEMA dw OWNER TO arsia_migrator;
ALTER SCHEMA qa OWNER TO arsia_migrator;

ALTER TABLE meta.source OWNER TO arsia_migrator;
ALTER TABLE meta.resource OWNER TO arsia_migrator;
ALTER TABLE meta.batch OWNER TO arsia_migrator;
ALTER TABLE meta.current_release OWNER TO arsia_migrator;
ALTER TABLE raw.record OWNER TO arsia_migrator;
ALTER TABLE rv.hub_crash OWNER TO arsia_migrator;
ALTER TABLE rv.hub_unit OWNER TO arsia_migrator;
ALTER TABLE rv.sat_crash OWNER TO arsia_migrator;
ALTER TABLE rv.sat_unit OWNER TO arsia_migrator;
ALTER TABLE rv.link_crash_unit OWNER TO arsia_migrator;
ALTER TABLE canonical.crash OWNER TO arsia_migrator;
ALTER TABLE canonical.unit OWNER TO arsia_migrator;
ALTER TABLE dw.dim_source OWNER TO arsia_migrator;
ALTER TABLE dw.dim_month OWNER TO arsia_migrator;
ALTER TABLE dw.dim_severity OWNER TO arsia_migrator;
ALTER TABLE dw.fact_crash OWNER TO arsia_migrator;
ALTER TABLE qa.check_result OWNER TO arsia_migrator;

GRANT USAGE ON SCHEMA meta, raw, rv, canonical, dw, qa
    TO arsia_loader;

GRANT SELECT, INSERT
ON TABLE
    meta.source,
    meta.resource,
    meta.batch,
    meta.current_release,
    raw.record,
    rv.hub_crash,
    rv.hub_unit,
    rv.sat_crash,
    rv.sat_unit,
    rv.link_crash_unit,
    canonical.crash,
    canonical.unit,
    dw.dim_source,
    dw.dim_month,
    dw.dim_severity,
    dw.fact_crash,
    qa.check_result
TO arsia_loader;

GRANT UPDATE (status, finished_at, error_details)
ON TABLE meta.batch
TO arsia_loader;

GRANT UPDATE (batch_id, batch_status, switched_at)
ON TABLE meta.current_release
TO arsia_loader;

SET LOCAL ROLE arsia_migrator;

CREATE SCHEMA published;

CREATE VIEW published.current_release
WITH (security_barrier = true, security_invoker = false)
AS
SELECT
    dataset_kind,
    batch_id,
    batch_status,
    switched_at
FROM meta.current_release;

CREATE VIEW published.current_source
WITH (security_barrier = true, security_invoker = false)
AS
SELECT
    release.dataset_kind,
    release.switched_at,
    source.batch_id,
    source.source_id,
    source.source_name,
    source.jurisdiction_code,
    source.release_label,
    source.release_scope
FROM meta.current_release AS release
JOIN dw.dim_source AS source
    ON source.batch_id = release.batch_id;

CREATE VIEW published.current_severity
WITH (security_barrier = true, security_invoker = false)
AS
SELECT
    release.dataset_kind,
    release.switched_at,
    severity.batch_id,
    severity.source_id,
    severity.severity_code,
    severity.severity_label,
    severity.definition_version,
    severity.definition_text
FROM meta.current_release AS release
JOIN dw.dim_severity AS severity
    ON severity.batch_id = release.batch_id;

CREATE VIEW published.current_crash
WITH (security_barrier = true, security_invoker = false)
AS
SELECT
    release.dataset_kind,
    release.switched_at,
    crash.*
FROM meta.current_release AS release
JOIN canonical.crash AS crash
    ON crash.batch_id = release.batch_id;

CREATE VIEW published.current_unit
WITH (security_barrier = true, security_invoker = false)
AS
SELECT
    release.dataset_kind,
    release.switched_at,
    unit.*
FROM meta.current_release AS release
JOIN canonical.unit AS unit
    ON unit.batch_id = release.batch_id;

CREATE VIEW published.current_fact_crash
WITH (security_barrier = true, security_invoker = false)
AS
SELECT
    release.dataset_kind,
    release.switched_at,
    fact.*
FROM meta.current_release AS release
JOIN dw.fact_crash AS fact
    ON fact.batch_id = release.batch_id;

CREATE VIEW published.current_qa_result
WITH (security_barrier = true, security_invoker = false)
AS
SELECT
    release.dataset_kind,
    release.switched_at,
    result.*
FROM meta.current_release AS release
JOIN qa.check_result AS result
    ON result.batch_id = release.batch_id;

RESET ROLE;

REVOKE ALL ON SCHEMA meta, raw, rv, canonical, dw, qa
    FROM arsia_reader;
REVOKE ALL ON ALL TABLES IN SCHEMA meta, raw, rv, canonical, dw, qa
    FROM arsia_reader;

GRANT USAGE ON SCHEMA published TO arsia_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA published TO arsia_reader;

ALTER DEFAULT PRIVILEGES FOR ROLE arsia_migrator
IN SCHEMA rv, canonical, dw, qa
REVOKE ALL ON TABLES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE arsia_migrator
IN SCHEMA rv, canonical, dw, qa
GRANT SELECT, INSERT ON TABLES TO arsia_loader;

ALTER DEFAULT PRIVILEGES FOR ROLE arsia_migrator
IN SCHEMA published
REVOKE ALL ON TABLES FROM PUBLIC;

ALTER DEFAULT PRIVILEGES FOR ROLE arsia_migrator
IN SCHEMA published
GRANT SELECT ON TABLES TO arsia_reader;

COMMENT ON ROLE arsia_migrator IS
    'NOLOGIN owner for ARSIA schemas and migrations; assumed by arsia_owner.';
COMMENT ON ROLE arsia_reader IS
    'Read-only account restricted to current successful published batches.';
COMMENT ON SCHEMA published IS
    'Reader boundary exposing only mode-specific current successful releases.';
COMMENT ON VIEW published.current_release IS
    'Current successful official or synthetic batch pointer visible to readers.';
COMMENT ON VIEW published.current_source IS
    'Source dimensions from the current successful batch for each dataset kind.';
COMMENT ON VIEW published.current_severity IS
    'Source-specific severity definitions from current successful batches.';
COMMENT ON VIEW published.current_crash IS
    'Canonical crashes from current successful batches only.';
COMMENT ON VIEW published.current_unit IS
    'Canonical units from current successful batches only.';
COMMENT ON VIEW published.current_fact_crash IS
    'Analytical crash facts from current successful batches only.';
COMMENT ON VIEW published.current_qa_result IS
    'Quality results from current successful batches only.';

COMMIT;
