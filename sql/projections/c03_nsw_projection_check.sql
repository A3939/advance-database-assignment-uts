-- Reconcile only this batch/source/release, preserving other projections.
WITH c AS (
 SELECT * FROM pg_temp.arsia_i_crash WHERE batch_id=%(batch_id)s::uuid
 AND source_id=%(source_id)s AND release_scope=%(release_scope)s
), u AS (
 SELECT * FROM pg_temp.arsia_i_unit WHERE batch_id=%(batch_id)s::uuid
 AND source_id=%(source_id)s AND release_scope=%(release_scope)s
)
SELECT
 (SELECT count(*) FROM c), (SELECT count(*) FROM u),
 (SELECT count(*) FROM (SELECT crash_key FROM c GROUP BY crash_key HAVING count(*)>1) d),
 (SELECT count(*) FROM (SELECT unit_key FROM u GROUP BY unit_key HAVING count(*)>1) d),
 (SELECT count(*) FROM u LEFT JOIN c USING (crash_key) WHERE c.crash_key IS NULL),
 (SELECT count(*) FROM c WHERE is_fatal_crash AND fatal_crash_eligible),
 (SELECT sum(fatality_count) FROM c WHERE fatality_eligible),
 (SELECT sum(casualty_count) FROM c WHERE casualty_eligible),
 (SELECT count(*) FROM c WHERE map_eligible),
 (SELECT count(*) FROM u WHERE unit_type_code IS NULL),
 (SELECT count(*) FROM u WHERE count_eligible AND unit_type_code IS NULL);
