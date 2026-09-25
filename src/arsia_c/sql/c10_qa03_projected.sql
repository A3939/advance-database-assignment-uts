-- Keep all current-batch rows, including unexpected source/release identities.
SELECT 'crash',to_jsonb(c) FROM pg_temp.arsia_i_crash c WHERE batch_id=%s::uuid
UNION ALL SELECT 'unit',to_jsonb(u) FROM pg_temp.arsia_i_unit u WHERE batch_id=%s::uuid;
