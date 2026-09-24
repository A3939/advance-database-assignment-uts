SELECT
 (SELECT count(*) FROM pg_temp.c45_vehicle WHERE NULLIF(payload->>'VEHICLE_TYPE','') IS NOT NULL
  AND NOT %(unit_types)s::jsonb ? (payload->>'VEHICLE_TYPE')),
 (SELECT count(*) FROM pg_temp.c45_crash WHERE NULLIF(payload->>'NO_OF_VEHICLES','') IS NOT NULL
  AND NOT ((payload->>'NO_OF_VEHICLES') ~ '^[0-9]+$' AND pg_input_is_valid(payload->>'NO_OF_VEHICLES','integer')));
