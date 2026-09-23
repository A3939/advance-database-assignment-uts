BEGIN;

CREATE ROLE arsia_loader
    LOGIN
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION;

GRANT CONNECT ON DATABASE arsia TO arsia_loader;
GRANT USAGE ON SCHEMA meta, raw TO arsia_loader;

GRANT SELECT, INSERT
ON TABLE meta.source, meta.resource, raw.record
TO arsia_loader;

COMMENT ON ROLE arsia_loader IS
    'Restricted account for B08 source registration and Raw loading.';

COMMIT;
