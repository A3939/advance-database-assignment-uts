# B14: recover an interrupted run

[`recovery.py`](../src/arsia_ingest/recovery.py) resolves one saved run without starting another build. The state handling is implemented and tested with simulated database replies. Real recovery still needs A's batch/release tables and E's publication integration.

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

## Validation and remaining inputs

Run the focused tests in the existing environment:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_recovery.py
```

The tests include actual `run_build()` receipts for lost registration, publication and failure COMMIT replies, with both committed and uncommitted simulated outcomes. They also cover repeated recovery, replaced successful releases, evidence/state mismatches, guarded updates and failures during recovery itself. Database state replies are simulated throughout these B14 tests.

The [2026-09-21 receipt](evidence/b14-recovery-validation-2026-09-21.json) records the final code/document hashes and these full-suite results:

| Environment | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Original `.venv`, no test DSN | 485 | 13 | 0 |
| Existing driver environment with PostgreSQL | 498 | 0 | 0 |

All 69 new B14 tests passed in both runs, including the CLI checks. The 13 real database tests belong to B08, B11 and B12; they do not validate recovery SQL. No dependencies or migrations were added. Existing receipts are unchanged. The isolated database was left empty, with no remaining test lock, and its container was stopped.

For real validation, A must provide `meta.batch`, `meta.current_release` and loader schema access, SELECT privileges and the required batch UPDATE/row-lock permissions. E's real publication must commit the successful batch, layers and pointer together through B. We still need to reproduce lost COMMIT replies and recovery against that environment. The current three-table test database cannot validate those operations.
