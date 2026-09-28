# C03/C06/C09 performance backport

This brings the C changes from [B PR #35](https://github.com/A3939/advance-database-assignment-uts/pull/35)
back to `yue/role-c`, based on `6987e604bb93809aa94a736085c3e8320452461d`.
Fresh, large batches could trigger repeated scans before PostgreSQL had useful
statistics. The business rules and VIC restrictions stay the same.

- C03 stages the complete selected NSW files, indexes native keys and analyzes
  only temporary tables. Keys, duplicates and orphans are checked before years.
- C06 stages the complete selected Accident/Vehicle/Person files. Its SQL keeps
  the same diagnostics, including invalid and out-of-scope records.
- C09 uses a bounded parent lookup with batch, source, release and crash key.
  An existing parent with the wrong native identity still fails.

Paths stay under `src/arsia_c/`: `projections/nsw.py`, `person_checks.py` and
`canonical_validation.py`. SQL copies in `sql/` and the package are synchronized.
The C10 fragment now records the changed C06 hashes. Public callbacks still use
the caller's transaction. Direct C03/C06 SQL needs the temporary inputs prepared
by its Python entry; use those entries in integrations.

## Run

Use Python 3.12, Docker and a clone with the pinned Git objects below. Each
output directory must be new. These commands create and remove private
PostgreSQL 16 containers; they do not use a shared database.

```sh
git fetch origin
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-c06.txt
.venv/bin/python -m pytest -q
.venv/bin/python tools/verify_c_performance.py --output .local/c-performance
.venv/bin/python tools/verify_c10_postgres.py --output .local/c10-performance
```

Both verifiers apply A `c0824da06b6e7b3f73c4ddeab2114d10b7156913` migrations
001–011. They use the test harness from B
`d5239db471e33ce30c137e9087f712c14cc6cea0`, audit A03 permissions before and after,
and run callbacks as `arsia_loader`. No permanent-table ANALYZE or grants are added.

The first verifier installs C's own wheel in a clean venv. It checks installed
file hashes and runs outside the checkout without source-path injection. The
second overlays the selected C files on the existing B component test base
`2750d8ea3f909cfacdc4cb10b35b87ffe729a468`. It uses real `FrozenManifest`,
`ModuleBinding`, context, evidence and QA persistence with a partial inventory.
It does not update C's embedded B runtime or freeze a complete platform build.

## Results — 28 September 2026

| Run | Result |
| --- | --- |
| C default suite | 720 passed, 307 skipped, 0 failed |
| Installed C component suite | 306 passed, 0 skipped; 185 real PostgreSQL tests |
| Installed B/C10 interface suite | 113 passed, 0 skipped; all use PostgreSQL |

The database runs overlap in 69 C06 cases; do not add them as unique tests.
They cover cold plans, native diagnostics, incomplete input, repeated calls,
wrong parents, caller rollback, QA07 year coverage and evidence persistence.
Both databases ended empty and both A03 audits passed.

Two old test setup issues were also fixed: QA07 now skips before importing B
helpers when no database is configured, and the wheel test finds QA SQL in
`sql/qa`. The 16 real QA07 cases still run in the C10 verifier.
Versions, hashes and result counts are in [the receipt](c-performance-validation-2026-09-28.json).

These are synthetic component regressions. B's earlier full official replay is
recorded in PR #35; it was not repeated or relabelled as a C-branch full build.
No new data permissions, official publication or whole-project acceptance is claimed.

## Contribution and review

Role C wrote the original modules: [C03](https://github.com/A3939/advance-database-assignment-uts/commit/19c81ab1f30d1d0f49825f730815062723a57724),
[C06](https://github.com/A3939/advance-database-assignment-uts/commit/c816f5b48ffe0afccc8d6702b9b2b208073eeeb9)
and [C09](https://github.com/A3939/advance-database-assignment-uts/commit/d63814562ba5aeef7f2409c7e8f814c648c91638).
Peixian (Role B) supplied the performance repairs in
[`666606c`](https://github.com/A3939/advance-database-assignment-uts/commit/666606c7a755afd5941f24fbbdcb66ecf3feed74)
and [`7d92c87`](https://github.com/A3939/advance-database-assignment-uts/commit/7d92c87fe5410bc642f6e2133b80818eb27e72f7),
then backported them and adapted C's tests here. C's history is retained.

C should check the SQL copies, unchanged diagnostic rules and transaction
ownership, then review and merge the PR into `yue/role-c`. Pull that branch after
merging. No new S0 definitions or source files are needed for these tests.
Other roles' work and dashboard delivery remain outside this PR.
