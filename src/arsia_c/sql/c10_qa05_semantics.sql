-- Independently derived Raw semantics are checked against persisted crashes too.
SELECT to_jsonb(c) FROM canonical.crash c WHERE batch_id=%s::uuid;
