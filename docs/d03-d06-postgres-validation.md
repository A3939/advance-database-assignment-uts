# D03-D06 PostgreSQL 16 validation

This receipt records the local database acceptance run for Role D at commit
`98cc5a3dafc1250373b0e3bddee9cc5642346ad5` on 25 September 2026.

## Environment and result

- PostgreSQL 16 ran in the pinned container image recorded in
  `evidence/d03-d06-postgres-validation-2026-09-25/environment.json`.
- The runner applied migrations 001-011 and deployed the D05 and D06 SQL.
- All 16 PostgreSQL integration cases for D03, D04, D05 and D06 passed.
- Result: 16 passed, 0 failed, 0 errors, 0 skipped.
- Application operations ran as `arsia_loader`. The test owner was used only
  to inject deliberately invalid rows for rollback and blocking checks; the
  loader's denied UPDATE privilege on `dw.fact_crash` was verified.
- The disposable database container and network were removed. No persistent
  volume was created and no publication was performed.

The complete receipt is in
`docs/evidence/d03-d06-postgres-validation-2026-09-25/`. It contains the
database setup log, pytest log and XML, exact input hashes, resolved container
images, summary, and cleanup record. The receipt can be reproduced with:

```powershell
python tools/verify_d03_d06_postgres.py --output-dir <evidence-directory>
```

## Scope boundary

This run validates D03-D06 against the currently integrated NSW C09 path. It
also checks D04's manifest-driven objects for every configured source and year.
It does not claim populated VIC/QLD Canonical projections or D06's final six
populated S0 source/severity groups. Those end-to-end checks require the C04
and C05 projections to be integrated into the same B transaction and batch.
