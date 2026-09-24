# D03 crash fact loading

`arsia_d03.runner_callback(connection, context)` is the combined DW callback.
It runs the reviewed D02 dimension loader first and then loads exactly one
`dw.fact_crash` row for every `canonical.crash` row in the selected batch on
the same caller-owned transaction.

## Fixed inputs and boundary

- Integration base: `peixian/dev` at
  `3af00089c94d309d5ceecb0b2e961eaef24b15e8`.
- Canonical implementation: reviewed C09 from PR #9, including A06 and its
  PostgreSQL acceptance checks.
- Dimension implementation: reviewed D02 from PR #6.
- Schema: A migrations 001 through 011, especially
  `sql/migrations/007_warehouse.sql`.

D03 reads only `canonical.crash`. It does not read Raw, Vault or
`canonical.unit`, and it does not recompute source measures or eligibility.
Raw and location lineage remain traceable through the complete Canonical key;
the fixed fact schema intentionally adds no uncontracted lineage columns.

## Loading and reconciliation

Before insertion, D03 checks that every Canonical crash has:

- a D02 Source row for the same batch and release scope;
- a source-specific Severity row with the same definition version; and
- a Month row when `occurrence_month` is known.

The loader copies all matching measures, flags and coordinates unchanged.
It derives `month_id = occurrence_year * 100 + occurrence_month` only when the
Canonical month is present; year-only crashes retain `month_id=NULL`.

After insertion, a full-key reconciliation checks the complete
`batch_id/source_id/release_scope/crash_key` set and every shared fact field
with `IS DISTINCT FROM`, so NULL differences are visible. Missing, extra or
changed rows fail with `D03_DATABASE_MISMATCH`. Repeating the callback may
reuse identical facts but cannot hide a conflicting row.

## Evidence and transaction ownership

The callback returns dimension and fact counts and writes:

- `d02-dimensions.json` from D02; and
- `d03-fact-crash.json` with fact/source counts and reconciliation flags.

The module does not commit, roll back, close the connection or publish a
batch. B10 owns those operations. Any D03 failure therefore rolls back D02,
D03 and the earlier stages together.

## Tests

The non-database suite checks blocking contracts and exact reconciliation
control flow. `tests/test_d03_postgres.py` is opt-in and must run against the
team's migrated PostgreSQL 16 database through `ARSIA_TEST_DSN`. It exercises
the real C09 → D02 → D03 path, confirms two crashes remain two facts despite
three Unit rows, checks the known/unknown month cases, idempotence, definition
conflicts and caller rollback.

No DSN means the PostgreSQL cases are skipped and D03 is not accepted as fully
database-validated.
