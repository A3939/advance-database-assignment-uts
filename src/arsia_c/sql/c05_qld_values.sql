CREATE TEMP TABLE c45_values ON COMMIT DROP AS
SELECT *, (payload->>'Crash_Year')::integer AS year,
 (%(month_map)s::jsonb->>btrim(NULLIF(payload->>'Crash_Month','')))::integer AS month,
 NULL::date AS day, CASE WHEN NULLIF(payload->>'Crash_Month','') IS NULL THEN 'year' ELSE 'month' END AS precision,
 payload->>'Crash_Severity' AS severity,
 NULLIF(payload->>'Count_Casualty_Fatality','')::integer AS killed,
 CASE WHEN NULLIF(payload->>'Count_Casualty_Fatality','') IS NOT NULL
        AND NULLIF(payload->>'Count_Casualty_Hospitalised','') IS NOT NULL
        AND NULLIF(payload->>'Count_Casualty_MedicallyTreated','') IS NOT NULL
        AND NULLIF(payload->>'Count_Casualty_MinorInjury','') IS NOT NULL
      THEN NULLIF(payload->>'Count_Casualty_Total','')::integer END AS casualties,
 CASE WHEN pg_input_is_valid(payload->>'Crash_Latitude','numeric') THEN (payload->>'Crash_Latitude')::numeric END AS lat,
 CASE WHEN pg_input_is_valid(payload->>'Crash_Longitude','numeric') THEN (payload->>'Crash_Longitude')::numeric END AS lon
FROM pg_temp.c45_crash;
