-- Check the complete source BEFORE casts and analysis filtering (PostgreSQL 16).
SELECT
 count(*) FILTER (WHERE CASE WHEN %(state)s='VIC' THEN
   COALESCE(NOT (payload->>'ACCIDENT_DATE' ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                AND pg_input_is_valid(payload->>'ACCIDENT_DATE','date')), true)
 ELSE COALESCE(NOT (payload->>'Crash_Year' ~ '^[0-9]{4}$'
      AND CASE WHEN pg_input_is_valid(payload->>'Crash_Year','integer')
               THEN (payload->>'Crash_Year')::integer BETWEEN 1 AND 9999 ELSE false END),true) END),
 count(*) FILTER (WHERE %(state)s='QLD' AND NULLIF(payload->>'Crash_Month','') IS NOT NULL
                 AND NOT %(month_map)s::jsonb ? btrim(payload->>'Crash_Month')),
 count(*) FILTER (WHERE NULLIF(payload->>%(severity_field)s,'') IS NOT NULL
                 AND NOT %(severity_map)s::jsonb ? (payload->>%(severity_field)s)),
 count(*) FILTER (WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(%(count_fields)s::jsonb) f
                 WHERE NULLIF(payload->>f,'') IS NOT NULL AND
                 NOT ((payload->>f) ~ '^[0-9]+$' AND pg_input_is_valid(payload->>f,'integer')))),
 count(*) FILTER (WHERE (SELECT sum(CASE WHEN pg_input_is_valid(payload->>f,'integer')
                         THEN (payload->>f)::integer::bigint END)
                        FROM jsonb_array_elements_text(%(count_fields)s::jsonb) f
                        WHERE f <> 'Count_Casualty_Total') > 2147483647)
FROM pg_temp.c45_crash;
