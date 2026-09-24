BEGIN;

SET ROLE arsia_migrator;

CREATE OR REPLACE FUNCTION rv.encode_business_key(
    VARIADIC components text[]
)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
AS $$
DECLARE
    component text;
BEGIN
    IF components IS NULL OR cardinality(components) = 0 THEN
        RAISE EXCEPTION
            'business key must contain at least one component'
            USING ERRCODE = '22023';
    END IF;

    FOREACH component IN ARRAY components LOOP
        IF component IS NULL OR btrim(component) = '' THEN
            RAISE EXCEPTION
                'business key components must be non-null and non-blank'
                USING ERRCODE = '22023';
        END IF;
    END LOOP;

    RETURN to_jsonb(components)::text;
END;
$$;

COMMENT ON FUNCTION rv.encode_business_key(VARIADIC text[]) IS
    'Encodes ordered business-key components as PostgreSQL JSON-array text while preserving component text, case and leading zeros. Empty, NULL and whitespace-only components are rejected.';

REVOKE ALL
ON FUNCTION rv.encode_business_key(VARIADIC text[])
FROM PUBLIC;

GRANT EXECUTE
ON FUNCTION rv.encode_business_key(VARIADIC text[])
TO arsia_loader;

RESET ROLE;

COMMIT;
