-- Validate the full selected snapshot before casts or analysis-year filtering.
SELECT
 count(*) FILTER (WHERE payload->>'CRASH_ID' IS NULL OR payload->>'CRASH_ID' ~ '^[[:space:]]*$'),
 count(*) - count(DISTINCT payload->>'CRASH_ID'),
 count(*) FILTER (WHERE NOT COALESCE(payload->>'YEAR' ~ '^[0-9]{4}$'
   AND CASE WHEN pg_input_is_valid(payload->>'YEAR','integer')
            THEN (payload->>'YEAR')::integer BETWEEN 1900 AND 2100 ELSE false END, false)),
 count(*) FILTER (WHERE NOT COALESCE(payload->>'MONTH' ~ '^[0-9]{1,2}$'
   AND CASE WHEN pg_input_is_valid(payload->>'MONTH','integer')
            THEN (payload->>'MONTH')::integer BETWEEN 1 AND 12 ELSE false END, false)),
 count(*) FILTER (WHERE NULLIF(payload->>'SEVERITY','') IS NOT NULL
   AND NOT %(severity_map)s::jsonb ? (payload->>'SEVERITY')),
 count(*) FILTER (WHERE EXISTS (
   SELECT 1 FROM (VALUES ('FATALITIES'),('CASUALTIES')) f(name)
   WHERE NULLIF(payload->>name,'') IS NOT NULL
     AND NOT (payload->>name ~ '^[0-9]+$' AND pg_input_is_valid(payload->>name,'integer')))),
 count(*) FILTER (WHERE CASE
   WHEN pg_input_is_valid(payload->>'FATALITIES','integer')
    AND pg_input_is_valid(payload->>'CASUALTIES','integer')
   THEN (payload->>'FATALITIES')::integer > (payload->>'CASUALTIES')::integer ELSE false END)
FROM pg_temp.s8_crash;
