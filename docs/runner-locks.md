# B12: PostgreSQL session locks

The independent lock checks have passed on real PostgreSQL. They cover the runner's `busy` branch, session locks across transaction boundaries and lock release after an early failure. Repeated builds and full AT13 acceptance still need the team's build modules.

## What the tests check

[`test_runner_postgres.py`](../tests/test_runner_postgres.py) uses separate `arsia_loader` sessions and the two-integer key `(32113, 2)` from contract 04, L4. The expected key is declared independently of the runner. `pg_locks` confirms the owning backend, exclusive mode and two-integer lock form.

| Case | Observed result |
|---|---|
| Session lifecycle | A second session cannot acquire the lock before or after the owner's COMMIT and ROLLBACK. Closing the owner lets the second session acquire it. |
| Runner busy | With another session holding the lock after COMMIT, `run_build()` returns `busy`, exit code 2 and no batch ID. It only sets the session options, tries the lock, rolls back and closes. The owner's lock remains held. |
| Runner early failure | The runner acquires the lock, then a test exception stops it before reading batch history. It returns `failed`, rolls back and closes; another session can then acquire the lock. |

The recording wrapper passes queries and transaction calls to Psycopg unchanged. Business callbacks raise if called. The manifest contains test-only code files and an undeployed FP1 binding; no fingerprint or business result is supplied. The failure case injects a Python exception, not a database outage.

These tests make no table writes. The lifecycle case uses real transaction boundaries, but it does not run the registration transaction or downstream build. Closing a session releases its lock; fixture cleanup also closes every test connection if an assertion fails.

## Run and evidence

Use A's isolated PostgreSQL 16 test database with the three B08 tables and loader grants. Set `ARSIA_TEST_DSN` and keep the password in a protected `PGPASSFILE`. Check the current mapped port after restarting the local container; the DSN and passfile must agree.

The existing local environment can run the focused checks:

```sh
PYTHONDONTWRITEBYTECODE=1 \
artifacts/b08-db-reproduction-2026-09-20/venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_runner_postgres.py
```

Without a DSN, the tests skip. Configured connection or permission errors fail. To retain evidence, choose a new `--basetemp` directory and `--junitxml` filename; pytest can clear an existing base directory. Each test saves `lock-check.json`, and runner cases also retain the normal run evidence.

The [2026-09-21 receipt](evidence/b12-lock-validation-2026-09-21.json) records the environment, test results, backend IDs, lock observations, executed SQL and final file hashes. Local reports are under `artifacts/b12-lock-validation-2026-09-21/`. Existing B08/B11 evidence was preserved.

| Run | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Three focused lock tests on PostgreSQL | 3 | 0 | 0 |
| Full suite, original `.venv` without a DSN | 416 | 13 | 0 |
| Full suite, existing driver environment with PostgreSQL | 429 | 0 | 0 |

The full database run includes 13 real PostgreSQL tests: eight B08, two QA02 and three lock tests. Other build tests still use mocks. PostgreSQL was 16.15, Python 3.12.6 and Psycopg 3.3.6; no packages or migrations were added. The three B08 tables and matching session-lock count were unchanged at zero. The isolated container was stopped after testing and its volume retained.

## Remaining B12 work

- E's real FP1 and publication functions are needed to verify `no_change`, unchanged batch/pointer timestamps and rebuilding after a rule or code change.
- A's remaining schema and the A/C/D/E modules are needed to check the lock throughout registration, the complete build and publication. The fixed shared key is verified here; a complete official/synthetic pair of builds is not.
- B13 fault injection after Vault/DW/publication and [B14 state recovery](recovery.md) remain separate from these lock tests. B14 has simulated state tests; its real integration is still pending.
