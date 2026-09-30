# E02 — Interface register and ownership

Owner: E / Aditya
Baseline: peixian/dev integration inspected 2026-09-25

## E-owned interfaces

| ID | Interface | Producer / consumer | Current contract | Status |
|---|---|---|---|---|
| E03 | FP1 SQL function | E provides SQL; B runner consumes through FP1Operation | PostgreSQL 16, UTF-8, UTC; one jsonb argument; one lowercase SHA-256 text result | Implemented |
| E04 | Independent expectations | E reviews B07/S0 expectations independently | Resource counts, layers, metric rules and QA object model are independently checked | Implemented |
| E05 | Publication validator | E consumes frozen manifest + persisted QA results | Exact required-object coverage; no missing/unexecuted result may be treated as pass | Implemented |
| E06 | Publication gate | E called by B runner before final commit | Candidate must be registered, all required QA summaries/concrete objects valid, and current pointer must reference the candidate | Implemented |

## Existing cross-role bindings

- B input and Raw: src/arsia_ingest/qa_input.py and src/arsia_ingest/raw_load.py.
- B runner: src/arsia_ingest/runner.py.
- C callbacks are registered through BuildModules.project, BuildModules.canonical and BuildModules.qa_c.
- D callback is registered through BuildModules.dw and BuildModules.qa_d.
- E publication callback is registered through BuildModules.publish.
- E FP1 is registered separately as FP1Operation and must also appear in the frozen fp1 inventory component.

## Ownership rule

This register does not claim ownership of A/C/D code merely because the code is integrated into B. The integrated branches remain owned by their authors. E owns the FP1 contract, independent QA/publication validation and the publication pointer operation.

## Completion evidence

- SQL source: sql/e/fp1.sql
- FP1 adapter: src/arsia_ingest/fingerprint.py
- Independent expectations: config/e-independent-expectations.json
- QA/publication validator: src/arsia_ingest/publication.py
- Publication gate tests: tests/test_e_publication.py
