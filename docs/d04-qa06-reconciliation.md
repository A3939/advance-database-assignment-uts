# D04 QA06 row and aggregate reconciliation

`arsia_d04.runner_callback(connection, context)` is the Role D `qa_d`
callback for `QA06_RECONCILIATION`. It compares the selected batch's
`canonical.crash` rows with D03's `dw.fact_crash` rows and writes the results
to `qa.check_result` on B's caller-owned transaction.

## Coverage

The callback derives its required objects from the frozen manifest. It always
creates one `source_year:<source_id>:<YYYY>` result for every enabled source
and every configured analysis year, including years with zero crashes, plus a
`batch` summary. For the current three-source 2020–2024 S0 contract this is 15
source-year objects and one summary.

Each source-year records the twelve fixed QA06 metrics:

- missing and extra fact counts;
- NULL-safe shared-field mismatches;
- primary/location Raw lineage errors, checked against the frozen resource,
  file hash and parser identities;
- Source/Severity dimension and definition-version errors;
- crash, fatal-crash, fatality and casualty deltas; and
- the three corresponding known-count deltas.

Expected metric values are zero. The key comparison uses the complete
`batch_id/source_id/release_scope/crash_key` identity before calculating any
totals. Swapping values between two valid crash keys therefore blocks even
when every aggregate is unchanged. Unit rows are never read.

## Evidence and persistence

A blocked source-year writes a JSONL difference file in the supplied QA
evidence directory. Each entry includes the full identity, issue types,
Canonical expected row, actual fact row, and available primary/location Raw
resource, file hash, parser and row locator. The QA row references the detail
file by path, SHA256 and row count.

The callback uses B's existing `QAReport` and `write_results()` interface. It
does not commit, roll back, close the connection, publish a batch, or replace
an earlier QA result. E remains responsible for summary review and the
publication gate; B remains responsible for the transaction.

## Current integration boundary

- B base: `peixian/dev` at
  `a469ddae23fb420827185b59c25f63500f55da3a`.
- D03 input: `yihua/D03` at
  `e2a0c6e28a4dcef27659783efbe553c959bb55fc`.
- C04/C05 reviewed delivery: `yue/role-c` at
  `ad8baeddd3f6d2eeccdc2e31bafd71b687ad4da8`.

C04/C05 are present on C's branch but are not yet connected to B's complete
projection callback. D04 is source-generic and can run for the existing NSW
chain now. The included PostgreSQL tests exercise the real C09 → D03 → D04
NSW path and all manifest source-year objects. Full VIC/QLD execution is
pending B's integration of the new C projection callbacks.

## Validation

`tests/test_d04.py` validates result shape, empty-year coverage, blocking and
located evidence without claiming database execution. The opt-in
`tests/test_d04_postgres.py` requires the migrated PostgreSQL 16 test database
and `ARSIA_TEST_DSN`. It checks:

1. 15 source-year objects plus the batch summary;
2. a payload swap that preserves aggregates but changes crash associations;
3. a wrong source-year that produces both missing and extra objects;
4. definition-version errors, QA persistence and caller rollback.

If the PostgreSQL cases are skipped, D04 has not received database acceptance.

The four D04 PostgreSQL cases passed on PostgreSQL 16 as part of the 16-case
D03-D06 acceptance run recorded in
`docs/d03-d06-postgres-validation.md`. This validates the current NSW path and
the manifest-driven source/year coverage; the VIC/QLD boundary above remains.
