-- Parent checks cover ALL years; Node observations are deliberately not unique.
SELECT
 (SELECT count(*) FILTER (WHERE rv.encode_business_key(payload->>'ACCIDENT_NO',payload->>'NODE_ID') IS NULL) FROM pg_temp.c45_node),
 (SELECT count(*)-count(DISTINCT rv.encode_business_key(payload->>'ACCIDENT_NO',payload->>'VEHICLE_ID')) FROM pg_temp.c45_vehicle),
 (SELECT count(*) FROM pg_temp.c45_vehicle v LEFT JOIN pg_temp.c45_crash c
   ON v.payload->>'ACCIDENT_NO'=c.native_key WHERE c.raw_record_id IS NULL),
 (SELECT count(*) FROM pg_temp.c45_node n LEFT JOIN pg_temp.c45_crash c
   ON n.payload->>'ACCIDENT_NO'=c.native_key WHERE c.raw_record_id IS NULL);
