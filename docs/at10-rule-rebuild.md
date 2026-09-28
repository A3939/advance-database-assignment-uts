# AT10 rule rebuild

AT10 needs a rule-only change that makes S0's N2 known non-fatal while its people counts stay unknown. The old NSW adapter ignored that declaration. A new fingerprint was published, but N2's classification did not change.

The optional NSW mapping fields `missing_severity_code` and `missing_severity_reason` now apply to synthetic inputs only. The target must be a declared non-missing code. The existing mapping version and reason are stored in `quality_notes.severity_rule`. The test changes the mapping to `syn-at10-nsw-v2` and the resource contract to `s0-native-at10-v2`.

C03 reads the rule in SQL. C10 separately derives its expected classification from the frozen manifest and checks the saved reason. Default missing values stay unknown, `__MISSING__` keeps its definition, and official overrides are rejected. Native files, people counts and successful history are unchanged.

## Validation

- Base: `85f830ef1a909050af35d9036840dd4c6bfcd751`.
- Schema: A `c0824da06b6e7b3f73c4ddeab2114d10b7156913`, unchanged migrations 001–011 and A03 loader grants.
- Python 3.12.6; PostgreSQL 16.15, UTF-8, UTC; image digest `sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67`.
- Before: the original installed base ran the three new database cases: **2 failed, 1 passed**.
- After: the repaired wheel passed **71 tests, 0 skipped**: 50 PostgreSQL cases and 21 unit/config checks. A03 passed before and after; the private database was empty after cleanup.
- S0 and the changed batch both have 6 crashes and totals 2/3/7. Fatal-crash known-count changes from 5 to 6; fatality/casualty known-counts remain 5. Repeating the changed rule returns `no_change`.

Run from this checkout with Python 3.12 and Docker:

```sh
python3.12 -m venv /tmp/arsia-at10
/tmp/arsia-at10/bin/python -m pip install -r requirements-db.txt
/tmp/arsia-at10/bin/python -m pip install --no-deps --no-build-isolation .
/tmp/arsia-at10/bin/python tools/verify_at10_postgres.py --output /tmp/arsia-at10-results
```

Use a new output directory. The verifier checks installed package bytes, creates its own PostgreSQL 16 container, applies A's migrations and removes the container afterwards. It never uses a shared database. [Receipt](evidence/at10-rule-rebuild-2026-09-28.json) records tested file hashes and commands. Full local logs are under `artifacts/at10-rule-rebuild-20260928/` in the workspace.

## Ownership and review

Role C wrote the original C03/C10 modules; see the [C03 history](https://github.com/A3939/advance-database-assignment-uts/commit/4bef8834cee3c7f5b5b79fc635ba67da83730f15) and [C10 history](https://github.com/A3939/advance-database-assignment-uts/commit/7bfb08ee4b3b0740e554ae89c6286c39db17ead2). Existing B integration and assistance are recorded in [C10 integration](c10-integration.md). Peixian / Role B added this rule adapter, SQL change, independent QA check and regression tests during E acceptance work. Original commits remain in history.

Review the synthetic-only boundary, reason retention, unchanged official behavior and old/new batch comparisons. This fixes AT10 in B's integrated runtime. It is not a change to an official source rule or a claim of complete E/course acceptance; C's standalone branch still needs this change if it must run the same variant.
