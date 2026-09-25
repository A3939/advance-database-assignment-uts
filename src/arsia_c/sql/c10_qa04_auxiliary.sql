-- Persisted units must keep the same restricted eligibility and parent identity.
SELECT to_jsonb(u) FROM canonical.unit u WHERE batch_id=%s::uuid;
