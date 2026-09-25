# B10 local validation

Checked on 2026-09-25, on `peixian/dev` at `3af00089c94d309d5ceecb0b2e961eaef24b15e8` plus the changes in this delivery. The receipt records the validation state before commit and push. B10 still needs a complete build with the team's real modules before it can be marked complete.

## Changes

- Start each runner-owned transaction at READ COMMITTED. A connection configured for REPEATABLE READ could otherwise keep an old view of batch history after a lock handover. The setting is repeated after registration commits and build rollbacks.
- Save UUID, Decimal and date values safely in failure evidence. Cyclic or unsupported diagnostics also produce valid JSON, so they do not prevent the failed status from being recorded.
- Include the returned input fingerprint in every candidate commit marker and outcome. Recovery can check it even when `result.json` is missing.
- Allow the existing `requirements-db.txt` in B09 code inventory. The partial A/C inventory now hashes the database and test requirements alongside the actual code. It still has `final_platform: false`.

No migration, loader grant or business rule changed.

## Results

| Run | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Targeted runner, recovery, manifest and inventory tests | 208 | 0 | 0 |
| Installed-wheel default suite | 615 | 155 | 0 |
| Installed-wheel PostgreSQL suite | 377 | 0 | 0 |

The suites overlap. The PostgreSQL suite includes unit and package checks; 377 is not a count of database-only tests. Default skips need optional database or archive inputs.

The 8 new PostgreSQL tests check transaction isolation, existing-running-batch rejection in both dataset modes, visibility after commit/rollback, durable failure details, and protection of finished batches. The early-exit runner tests stop before FP1. Other lifecycle tests call the real helpers with clearly labelled fixture batches. None is a successful full B10 build.

The strengthened runner/recovery suite found 31 failing assertions against the original runner, with 93 passing. All 124 now pass. These failures cover the three runner problems above, not 31 separate bugs.

The database run used PostgreSQL 16.15, Python 3.12.6, psycopg 3.3.6 and A's migrations 001–011 from fix `c0824da06b6e7b3f73c4ddeab2114d10b7156913`. Tests ran as `arsia_loader`. The original A03 permission audit passed before and after. All 17 checked tables were empty after cleanup, and the private container was removed. No shared database or published release was changed.

## Reproduce

From the repository root, with Python 3.12 and Docker available, use fresh output directories:

```sh
python3.12 -m venv ../.venv-b10
../.venv-b10/bin/python -m pip install -r requirements-db.txt
../.venv-b10/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir ../b10-wheels
../.venv-b10/bin/python -m pip install --no-deps ../b10-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
../.venv-b10/bin/python -m pytest -q -p no:cacheprovider -o pythonpath= tests
../.venv-b10/bin/python tools/verify_ac_postgres.py --output ../b10-postgres-result
```

Unset `PYTHONPATH` and optional test DSNs before the default run. The verifier checks installed code and resources, creates its own PostgreSQL container, applies the migrations and records cleanup. It does not use a shared DSN.

The [receipt](evidence/b10-local-validation-2026-09-25.json) records versions, hashes and results. Full local logs are in `../artifacts/role-b10-local-20260924/`, relative to the repository root.

## Remaining work

The [later C/D integration](cd-integration.md) now includes C04/C05, the all-source dispatcher, D03 and D04. The table below describes the remaining full-build inputs; the test results above are unchanged.

| Owner | Needed for the full build |
|---|---|
| C | Complete C10 QA callback and persisted results. |
| D | D03/D04 are integrated. Query-side D05–D08 integration and reader validation are separate work. |
| E | Real E03 FP1 SQL with its version and deployment details; E06 publication gate and current-release operation. |
| B with C/D/E | Register the real callbacks, freeze the complete inventory, then test successful, failed and uncertain-commit builds through the full runner. |

S0 definitions and existing component tests are already available. No replacement FP1, empty callback or invented file hash was used to fill a missing stage.
