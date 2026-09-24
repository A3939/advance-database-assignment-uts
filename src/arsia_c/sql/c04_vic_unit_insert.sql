INSERT INTO pg_temp.arsia_i_unit
SELECT %(batch_id)s::uuid,%(source_id)s,%(release_scope)s,
 rv.encode_business_key(v.payload->>'ACCIDENT_NO',v.payload->>'VEHICLE_ID'),c.crash_key,v.raw_record_id,
 v.payload->>'VEHICLE_TYPE',%(unit_types)s::jsonb->>(v.payload->>'VEHICLE_TYPE'),%(statistical_scope)s,
 NOT %(official_vic)s AND NULLIF(v.payload->>'VEHICLE_TYPE','') IS NOT NULL,
 CASE WHEN %(official_vic)s OR NULLIF(v.payload->>'VEHICLE_TYPE','') IS NULL THEN
  jsonb_build_object('fields',jsonb_build_array(jsonb_build_object('field','count_eligible',
   'reason_code',CASE WHEN %(official_vic)s THEN 'definition_unconfirmed' ELSE 'missing' END,
   'raw_token',v.payload->>'VEHICLE_TYPE','contract_version',%(unit_contract_version)s::text))) ELSE '{}'::jsonb END
FROM pg_temp.c45_vehicle v JOIN pg_temp.c45_values c ON v.payload->>'ACCIDENT_NO'=c.native_key
WHERE c.year BETWEEN %(year_from)s AND %(year_to)s;
