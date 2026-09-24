# C09 Canonical loading

`arsia_c.canonical.load_canonical(connection, context)` loads the 24 crash and
11 real-unit fields from A06's current-batch Satellites. It uses B's supplied
connection without committing, rolling back, closing it, or publishing.

## Dependencies

This delivery starts at Role C `cc39c6ffda18ea02ce1b393beaded1e5d6379176`,
including [C03 PR #7](https://github.com/A3939/advance-database-assignment-uts/pull/7).
The previously missing `src/arsia_ingest/vault_load.py` and its original tests
are included unchanged from A's
[`d30405e`](https://github.com/A3939/advance-database-assignment-uts/commit/d30405eab42ffb2475dea9f7322e7b803b879963).

Use PostgreSQL 16 and A's migrations 001–011, including the A05 key function
and A02 fixes in [PR #5 / `c0824da`](https://github.com/A3939/advance-database-assignment-uts/commit/c0824da06b6e7b3f73c4ddeab2114d10b7156913).
Tests use the normal non-superuser `arsia_loader`.

The context supplies a running `batch_id`, B09 selected `sources`, `files`,
`rules.contracts`, and `evidence.write_json`. Each selected crash/unit/Node
resource needs one confirmed or synthetic-defined contract matching its exact
file identity and release. Ordered native keys and parent/Node join fields
come from that contract. Missing, duplicate and draft contracts are rejected.
Include C09, its validation helper and A06 in the actual B09 component inventory
when assembling the full build.

## Boundary checks

Before insertion, C09 verifies selected resource/hash/parser, entity kind,
batch/source/release, primary Raw keys using A05's SQL encoder, and every
unit's complete Link and parent. Direct location lineage must use the same
crash Raw row; Node lineage must reference the selected Node resource and
exact accident/Node join fields. Checks also cover attribute keys and types,
date precision, NULL/eligibility consistency, unchanged numeric coordinates
and structured `quality_notes`. Only a running empty candidate may be loaded;
a retry needs B's new batch ID.

Raw reads verify identities and join fields only. Measures, classifications,
coordinates and reasons come from Satellite attributes. C07 still owns Node
observation agreement, CRS evidence and representative selection; C10 owns
persisted QA.

After insertion, full key, Raw-lineage and attribute comparisons verify the
actual Canonical tables against all current-batch Satellites. Missing Links
cannot silently hide units. Evidence is written only after reconciliation.
Failures propagate to B for complete transaction rollback; successful history
is never modified.

## Reproduce

Use a disposable database with the migrations above:

```sh
python -m pip install -r requirements-dev.txt 'psycopg[binary]==3.3.6'
export ARSIA_TEST_DSN='postgresql://arsia_loader:YOUR_TEST_PASSWORD@localhost:YOUR_PORT/arsia'
python -m pytest -q tests/test_c09_canonical.py tests/test_c09_postgres.py tests/test_c09_acceptance_postgres.py
python -m pytest -q tests/test_c09_canonical.py tests/test_c09_postgres.py tests/test_c09_acceptance_postgres.py tests/test_c03_nsw_projection.py tests/test_c03_nsw_postgres.py tests/test_vault_load_postgres.py
```

No DSN means database tests are skipped, not accepted. An invalid configured
DSN, missing driver/migrations, wrong version or privileges fails explicitly.
Database test writes are rolled back.

## Verified scope

PostgreSQL 16.15: **65 C09 tests passed, no skips** (38 unit / 27 database).
Related C09/C03/A06 checks: **139 passed**. A separate 65-test run used B's
actual `peixian/dev` at `bc4ed6b000a354babe3cab65e5b5028a41ae304a`.
The validation receipt records versions, input hashes and limitations.

The actual B08 → C03 → A06 → C09 NSW path loads 19 native S0 Raw rows and
produces 2 NSW crashes, 3 units and 1 mapped crash. A separate three-state
boundary test sends C01's expected projections through real B08/A06/C09:
6 crashes, 6 units, 4 mapped crashes, no QLD units, and all 24/11 fields equal.
That boundary test does not execute C04/C05. Tests also cover malformed values,
selected-file and Node failures, missing Links, history, shared rollback and
more than 1,000 inserted rows. Five relevant regressions fail on original C09.

This is C09 component delivery. Real FP1/full inventory, official-data acceptance,
C10 persisted QA, DW and publication remain separate integration work. C's
review and merge remain required.
