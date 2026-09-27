# E05 — QA protocol and object completeness

Owner: Role E / Aditya

E05 validates the publication inputs against the shared team-v1.1 QA contract. The validator in src/arsia_ingest/publication.py derives the required object set from the frozen manifest rather than accepting a caller-supplied count.

Required coverage:

- QA01_INPUT: one file object per manifest file.
- QA02_RAW: one file object per manifest file.
- QA03_PROJECTED: every crash/unit resource.
- QA04_AUXILIARY: every unit/person_raw/node_raw resource.
- QA05_SEMANTICS: every source.
- QA06_RECONCILIATION: every source × every analysis year, including zero-crash years.
- QA07_LOCATION: every source × every analysis year, including zero-crash years.
- Every rule also requires a batch summary object.

The validator rejects missing or extra concrete objects, malformed actual/expected JSON, non-zero expected violations, block results, invalid limited results and non-zero affected counts on pass. Only QA07 may be limited.

A missing or unexecuted result is never converted to pass. Successful results remain immutable for the batch; retries use a new batch.
