-- Preserve native identity and Node matching fields in the temporary staging rows.
CREATE TEMP TABLE c45_values ON COMMIT DROP AS
SELECT *, extract(year FROM (payload->>'ACCIDENT_DATE')::date)::integer AS year,
 extract(month FROM (payload->>'ACCIDENT_DATE')::date)::integer AS month,
 (payload->>'ACCIDENT_DATE')::date AS day, 'day'::text AS precision,
 payload->>'SEVERITY' AS severity,
 NULLIF(payload->>'NO_PERSONS_KILLED','')::integer AS killed,
 (NULLIF(payload->>'NO_PERSONS_KILLED','')::bigint + NULLIF(payload->>'NO_PERSONS_INJ_2','')::bigint
   + NULLIF(payload->>'NO_PERSONS_INJ_3','')::bigint)::integer AS casualties,
 NULL::numeric AS lat, NULL::numeric AS lon
FROM pg_temp.c45_crash;
