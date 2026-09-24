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
python tools/verify_d03_d06_postgres.py --output <evidence-directory>
```

## Three-source integration receipt

This run validates D03-D06 against the currently integrated NSW C09 path. It
also checks D04's manifest-driven objects for every configured source and year.

A second disposable PostgreSQL 16 run combined D commit
`144fb80e27e7004e5647cacbb245603f6f2d7d36` with C delivery
`ad8baeddd3f6d2eeccdc2e31bafd71b687ad4da8`. All 144 selected C component and
combined C/D tests passed with 0 failures, errors, or skips. The actual S0 path
was B08 Raw -> C03/C04/C05 -> A06 Vault -> C09 Canonical -> D03/D04/D05/D06.
It produced six crashes, six units, six facts, 16 passing QA06 rows, and the
six required populated source/severity groups.

The receipt, combined test, verifier, environment, logs, exact input hashes,
and cleanup record are in
`docs/evidence/c45-d03-d06-postgres-validation-2026-09-25/`. This was a local
integration overlay of the two attributed deliveries. It did not copy C's
implementation into D's branch, update B's production module bindings, publish
a release, or create a persistent database volume.
