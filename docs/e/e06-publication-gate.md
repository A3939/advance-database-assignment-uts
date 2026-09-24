# E06 — Publication gate and current pointer

Owner: Role E / Aditya

The publication callback is src/arsia_ingest/publication.py. It is designed for B's caller-owned transaction and is registered as BuildModules.publish.

Gate sequence:

1. Confirm the candidate exists in meta.batch and is still running.
2. Confirm the stored manifest equals the frozen manifest supplied to the build.
3. Derive all required QA concrete objects from the manifest.
4. Require every concrete object plus every batch summary for QA01–QA07.
5. Reject block results, unexpected limited results, malformed evidence and non-zero violations.
6. Mark the candidate batch succeeded in the same transaction.
7. Switch meta.current_release to the candidate using the existing composite foreign key.
8. Return the seven-rule QA summary to B.

The existing migration 004_meta_batch.sql already supplies meta.batch and meta.current_release. E06 therefore does not duplicate the pointer schema; it supplies the missing gate operation.

Important: the final database commit remains owned by B. E06 changes database state inside B's transaction but never commits, rolls back or closes the connection.

Acceptance evidence should include the successful candidate batch ID, fingerprint, seven QA summaries, pointer row and commit result. Failure evidence should retain the blocked rule/object and must not advance current_release.
