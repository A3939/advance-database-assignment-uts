-- Exercise 011 through the installed function and copied CHECK constraints.
-- LIKE does not copy foreign keys; this smoke test does not test them.
BEGIN;
SET LOCAL ROLE arsia_loader;

DO $$
DECLARE
    component text;
BEGIN
    FOREACH component IN ARRAY ARRAY[NULL, '', ' ', E'\t\n', U&'\00A0', U&'\3000'] LOOP
        BEGIN
            PERFORM rv.encode_business_key(component);
            RAISE EXCEPTION 'accepted a blank business-key component';
        EXCEPTION WHEN invalid_parameter_value THEN
            NULL;
        END;
    END LOOP;
    IF rv.encode_business_key('0001', ' 01 ') <> '["0001", " 01 "]' THEN
        RAISE EXCEPTION 'changed a valid business key';
    END IF;
END $$;

CREATE TEMP TABLE a09_crash_checks
    (LIKE canonical.crash INCLUDING DEFAULTS INCLUDING CONSTRAINTS);
INSERT INTO a09_crash_checks
    (batch_id, source_id, release_scope, crash_key, raw_record_id,
     occurrence_year, date_precision, severity_code, severity_definition_version,
     latitude, longitude, location_crs, map_eligible, location_record_id)
VALUES
    (gen_random_uuid(), 'syn_a09', 'test', '["0001"]', gen_random_uuid(),
     2024, 'year', 'UNKNOWN', 'test', -33.86, 151.21, NULL, false, gen_random_uuid());

DO $$
DECLARE
    crs text;
    failed_constraint text;
BEGIN
    FOREACH crs IN ARRAY ARRAY[NULL, 'EPSG:4283'] LOOP
        BEGIN
            UPDATE a09_crash_checks SET map_eligible = true, location_crs = crs;
            RAISE EXCEPTION 'accepted map eligibility with invalid CRS';
        EXCEPTION WHEN check_violation THEN
            GET STACKED DIAGNOSTICS failed_constraint = CONSTRAINT_NAME;
            IF failed_constraint <> 'canonical_crash_map_eligibility_valid' THEN
                RAISE;
            END IF;
        END;
    END LOOP;
    UPDATE a09_crash_checks SET map_eligible = true, location_crs = 'EPSG:4326';
    UPDATE a09_crash_checks SET map_eligible = false, latitude = NULL,
        longitude = NULL, location_crs = NULL, location_record_id = NULL;
END $$;
ROLLBACK;
