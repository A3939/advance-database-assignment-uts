# B14: recover an interrupted run

[`recovery.py`](../src/arsia_ingest/recovery.py) resolves one saved run without starting another build. It now has real PostgreSQL 16 tests against A's fixed schema and original loader permissions. These use seeded test states. Recovery after a complete E publication still needs the real team pipeline.

## Entry point

```python
from arsia_ingest.recovery import recover_run

result = recover_run(
    connect=connect_loader,
    run_dir=original_run_directory,
    evidence_root="artifacts/builds",
)
print(result.as_dict())
```

`connect_loader()` must open a **new dedicated connection to the original run's database**, with `autocommit=False`. The saved evidence does not identify a database server, so the caller must choose the right one. Recovery owns this connection and closes it. Credentials stay in the connection setup.

The command-line entry accepts the same connection factory:

```sh
python -m arsia_ingest.recovery \
  --connect team_bindings:connect_loader \
  --run-dir 'artifacts/builds/synthetic/runs/REPLACE_WITH_RUN_ID' \
  --evidence-root artifacts/builds
```

Replace `REPLACE_WITH_RUN_ID` before running. `team_bindings` is supplied by the team; no default database connection is included. Normal `run_build()` still stops at `RECOVERY_REQUIRED` when it finds a running batch. Resolve that batch first, then start any retry as a new run.

## Saved input and decisions

Recovery reads `manifest.json` and `before-registration-commit.json` from the original `<mode>/runs/<run_id>/` directory. It also checks any publication/failure commit marker, `result.json` and `error.json`. Run/batch IDs, mode, UTC timestamps and stages must agree. Invalid input stops before connecting.

The original frozen manifest is compared with the database value, including JSON value types. Recovery does not rehash today's code or call FP1. A recorded fingerprint is checked when available; older commit markers did not store one. Recovery does not certify those fingerprints.

On the new connection, recovery uses READ COMMITTED, UTC and UTF8, takes session lock `(32113, 2)`, then locks the target batch row. It checks the current pointer for the same mode, including its joined batch state.

| Observed state | Decision |
|---|---|
| Lock occupied | `busy`; no state reads or writes. |
| `succeeded`, with a valid current release | Confirm success without writes. The current release may be a newer successful batch; no pointer is changed. |
| `failed` | Return the existing failure without changing its error or finish time. |
| `running`, with matching identity and manifest | The old session no longer holds the lock. Mark only this row failed, using status/fingerprint/manifest guards, and commit the recovery record. |
| No row, registration-only evidence | `not_registered` only if there is no later commit/error evidence and the result is absent or identifies registration COMMIT uncertainty. Contradictory diagnostic stages remain unknown. |
| Missing state after later stages, mismatched evidence or an invalid pointer | `unknown_commit`; do not change the batch. A successful batch with no current release is also left unresolved. |

SQL errors and uncertain rollback/COMMIT responses return `unknown_commit`. Recovery does not retry internally. A later call uses a fresh connection and queries again: an already failed or successful batch is left unchanged. No Raw records, QA rows or business tables are changed, and no build resumes from an intermediate stage.

## Results and evidence

`RecoveryResult` reports `resolution`, the original `run_id`, `batch_id` and `dataset_kind`, plus a new `recovery_id` and evidence path. `succeeded`, `failed` and `not_registered` have exit code 0 because the old run was resolved; `busy` is 2 and `unknown_commit` is 3. These are recovery outcomes, not new database statuses or full build results. No QA summary is invented.

Each attempt writes a new `<mode>/recoveries/<recovery_id>/` directory. It records original-file hashes, the observed state, any update decision, the recovery COMMIT marker and the result. Original run evidence stays unchanged and is checked again before the update. Driver exception text is omitted from diagnostics. If final file output fails after an acknowledged commit, the returned resolution remains known and includes the evidence error.

## Validation

Run the unit tests with Python 3.12:

```sh
python -m pytest -q tests/test_recovery.py
```

For the database checks, install a wheel in a separate environment. Docker must be running. From the repository root:

```sh
python3.12 -m venv ../b14-venv
../b14-venv/bin/python -m pip install -r requirements-dev.txt -r requirements-db.txt
../b14-venv/bin/python -m pip install .
../b14-venv/bin/python tools/verify_b14_postgres.py --output ../b14-validation
```

Use a new output directory each time. The verifier checks the installed package hashes, starts a private PostgreSQL 16 container on a random local port, applies migrations 001–011, and runs the original A03 audit before and after testing. It removes the container in `finally`. It does not connect to a shared database or add grants.

The [2026-09-25 receipt](evidence/b14-postgres-validation-2026-09-25.json) records the tested files and results. The selected suite passed **158 tests with no skips or failures**:

- 23 new real PostgreSQL recovery tests.
- Existing recovery, runner, session-lock and B10 lifecycle regression tests.

The new tests check abandoned runs, preserved success/failure records, newer release pointers, mismatched manifests/fingerprints, missing registration, advisory and row locks, READ COMMITTED, and the loader's actual permissions and foreign key. A fresh recovery call resolves both committed and uncommitted lost-reply cases. Original evidence, other batches, the pointer, a QA row and a dimension row stay unchanged. All 17 tables were empty and no advisory locks remained after cleanup.

Lost replies are injected before or after real psycopg commits; this is not a network-proxy test. A separate test terminates the real PostgreSQL backend before COMMIT and checks rollback and recovery on a new connection. No recovery runtime change was needed. The [B contribution note](contributions/b14-postgres.md) records this delivery.

The manifests come from the real `FrozenManifest` constructor and S0 definitions, with a labelled fixture code inventory. The digest and successful batch/pointer states are test fixtures, not E03 fingerprints or published releases. No FP1, C/D/E callback or full B10 build runs in this suite.

The [2026-09-21 receipt](evidence/b14-recovery-validation-2026-09-21.json) remains the historical unit-test record. Its database tests did not exercise recovery SQL.

## Remaining integration

A's required tables and grants are available in fixed commit `c0824da06b6e7b3f73c4ddeab2114d10b7156913`; no new A handoff is needed for these checks. B can now use the tested recovery entry point with a fresh loader connection to the original database.

Full acceptance still needs C's remaining QA callback and E's verified FP1/publication gate, then B's final inventory and complete build wiring. After that, B should repeat lost-registration, publication and failure-COMMIT recovery around the actual build. This component result does not mark a full platform build or official publication complete.
