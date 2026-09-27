-- E03 FP1 implementation for PostgreSQL 16.
CREATE SCHEMA IF NOT EXISTS e;

CREATE OR REPLACE FUNCTION e.fp1(jsonb)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
STRICT
AS $$
    SELECT pg_catalog.encode(
        pg_catalog.sha256(pg_catalog.convert_to($1::text, 'UTF8')), 'hex')
$$;

COMMENT ON FUNCTION e.fp1(jsonb) IS
    'FP1 SHA-256 fingerprint over the normalized manifest JSONB payload.';

REVOKE ALL ON FUNCTION e.fp1(jsonb) FROM PUBLIC;
GRANT USAGE ON SCHEMA e TO arsia_loader;
GRANT EXECUTE ON FUNCTION e.fp1(jsonb) TO arsia_loader;
