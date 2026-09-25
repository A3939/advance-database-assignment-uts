-- D03 facts supply actual counts, never expected crash/map populations.
SELECT to_jsonb(f) FROM dw.fact_crash f WHERE batch_id=%s::uuid;
