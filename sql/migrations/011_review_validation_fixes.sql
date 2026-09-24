BEGIN;

SET LOCAL ROLE arsia_migrator;

-- Upgrade databases that already applied 006. Validate existing rows too:
-- inconsistent map-eligible rows must be investigated, never silently rewritten.
ALTER TABLE canonical.crash
    DROP CONSTRAINT canonical_crash_map_eligibility_valid,
    ADD CONSTRAINT canonical_crash_map_eligibility_valid
        CHECK (
            NOT map_eligible
            OR (
                latitude IS NOT NULL
                AND longitude IS NOT NULL
                AND location_crs IS NOT NULL
                AND location_crs = 'EPSG:4326'
                AND location_record_id IS NOT NULL
            )
        );

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
    -- Unicode White_Space plus U+001C..U+001F, matching Python str.isspace().
    -- Use a fixed set so validation does not depend on the database locale.
    whitespace CONSTANT text :=
        U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680'
        || U&'\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000';
BEGIN
    IF components IS NULL OR cardinality(components) = 0 THEN
        RAISE EXCEPTION
            'business key must contain at least one component'
            USING ERRCODE = '22023';
    END IF;

    FOREACH component IN ARRAY components LOOP
        IF component IS NULL OR btrim(component, whitespace) = '' THEN
            RAISE EXCEPTION
                'business key components must be non-null and non-blank'
                USING ERRCODE = '22023';
        END IF;
    END LOOP;

    -- Whitespace removal is only a predicate above. Encode the original values.
    RETURN to_jsonb(components)::text;
END;
$$;

-- CREATE OR REPLACE preserves the owner and existing EXECUTE privileges.
COMMENT ON FUNCTION rv.encode_business_key(VARIADIC text[]) IS
    'Encodes ordered business-key components as PostgreSQL JSON-array text without changing valid IDs. Rejects NULL, empty and all-whitespace components using a locale-independent set matching Python str.isspace().';

COMMIT;
