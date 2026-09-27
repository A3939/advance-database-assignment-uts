# E06 — Publication gate

Owner: Role E / Aditya. Gate repairs and validation: Role B / Peixian.

Register `arsia_ingest.publication:publish` as B's `BuildModules.publish`,
with `src/arsia_ingest/publication.py` and version `e06-publication-v1.1`.
Include `publication_checks.py` and its existing B dependencies in the code
inventory. The callback uses B's connection, manifest, batch and fingerprint.

The gate locks the running candidate and checks its manifest and context.
It derives every required QA01–QA07 object, including empty source-years.
Missing objects, extra objects/rules and any blocking result stop publication.

For each object it checks the fixed metric keys, types, expected values,
evaluation coverage and evidence. File counts come from the manifest;
Canonical/DW counts provide an extra coverage check. C still owns the Raw
business-rule and exclusion checks. E does not replace those producers.
NULL expectations are limited to the agreed inapplicable/Node fields and
need reasons. VIC exceptions use the exact pinned restricted policy.

Evidence needs its producer, resolution, references and reason list. Detail
files must exist and match their SHA256 and record counts. References must
cover the checked object, not another file, source or year. Same-source parent
and child references can support a check, but cannot replace its own identity. Every QA07 limited
crash needs its stored location reason. Zero-crash coverage stays NULL.
The evidence paths must remain available to the gate during the transaction.

E recalculates each summary from concrete objects and rejects stale summaries.
Only valid QA07 results may be limited. It then marks the candidate succeeded,
switches `meta.current_release`, and returns seven summaries. B owns the final
commit. On error B must roll back; E never commits, rolls back or closes.

See [test scope, commands and review notes](e03-e06-review.md). Component tests
do not establish a final inventory freeze or official platform acceptance.
