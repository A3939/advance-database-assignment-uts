-- Read exact Raw identities only; projection output never supplies expectations.
SELECT r.raw_record_id::text,r.resource_id,r.row_locator,r.payload
FROM jsonb_to_recordset(%s::jsonb) f(source_id text,resource_id text,file_sha256 text,parser_version text)
JOIN raw.record r USING(source_id,resource_id,file_sha256,parser_version);
