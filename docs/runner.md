# B10: build runner

[`runner.py`](../src/arsia_ingest/runner.py) owns the connection, session lock and transactions. It reuses B08 loading, B09 manifest/FP1 and [B11 input checks](input-qa.md). Team modules must be registered explicitly; there are no default business functions.

The runner is ready for module integration. [Session contention and early cleanup](runner-locks.md) have real PostgreSQL tests. Build paths still use scripted replies and test callbacks; real FP1, publication and full B12–B14 acceptance remain unverified.

## Entry point

Call `run_build` from a team bindings module:

```python
from arsia_ingest.runner import BuildModules, ModuleBinding, run_build

modules = BuildModules(
    project=ModuleBinding(project, project_path, project_version),
    vault=ModuleBinding(vault, vault_path, vault_version),
    canonical=ModuleBinding(canonical, canonical_path, canonical_version),
    dw=ModuleBinding(dw, dw_path, dw_version),
    qa_c=ModuleBinding(qa_c, c_qa_path, c_qa_version),
    qa_d=ModuleBinding(qa_d, d_qa_path, d_qa_version),
    publish=ModuleBinding(publish, publish_path, publish_version),
)
result = run_build(
    connect=connect_loader, prepared_run=run_dir, manifest=frozen,
    project_root=project_root, inventory=inventory, modules=modules,
    fp1=fp1_operation, evidence_root="artifacts/builds",
    supported_mappings=accepted_mappings, official_reviews=source_reviews,
)
```

All names in this example are supplied bindings, not installed functions. `connect_loader()` must return a fresh, dedicated PostgreSQL connection with `autocommit=False` and tuple cursor rows. Do not return a pooled wrapper: `close()` must end the database session. Keep credentials in A's connection setup, outside manifests and evidence. The runner sets client encoding to UTF8 and the session timezone to UTC; the existing FP1 adapter checks A/E's exact PostgreSQL 16 patch and SQL binding.

`manifest` is a `FrozenManifest`. The runner rechecks actual inventory hashes and the prepared file set before database work. Each module's `code_path` must be in its corresponding inventory component; both QA callbacks use `qa`. Versions and paths are recorded in the run evidence. Authors remain responsible for listing their full code/SQL dependencies and matching the installed implementation.

For a command-line entry, expose a function returning the keyword arguments above:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m arsia_ingest.runner \
  --bindings team_bindings:build_request
```

`team_bindings` is the team's integration module. It is not included yet: A's three B08 tables are available, but the remaining schema and downstream functions are still needed. A missing binding fails explicitly. `python -m arsia_ingest` remains the native preparation command.

## Module interface

Each callback receives `(connection, context)` and runs its SQL without committing. Return values are ignored; publication is checked against database state.

The shared `ModuleConnection` exposes `autocommit` and `cursor()`. Cursors support `execute`, `executemany`, fetch methods, iteration, `rowcount` and `description`. The facade omits commit, rollback, close and `cursor.connection`. It prevents accidental lifecycle calls; trusted SQL must also avoid transaction control, session changes and advisory-lock operations.

`RunContext` contains:

```text
run_id, dataset_kind, batch_id, input_fingerprint,
previous_batch_id, manifest, evidence
```

Use `context.manifest.as_dict()` for a separate copy of the frozen definitions. Write module evidence with `context.evidence.write_json("counts.json", value)`. B supplies a separate stage directory; the writer returns a path, SHA256 and row count and refuses an existing filename. Modules can raise `IntakeError(code, message, **details)` with rule/object IDs, locators, actual/expected values and evidence references. Keep connection strings out of errors.

## Lifecycle

1. Acquire `pg_try_advisory_lock(32113, 2)` on the dedicated session. Both modes share this key. Contention returns `busy` without registering a batch.
2. Check for existing `running` batches and read the current release for this mode. Unresolved runs return `RECOVERY_REQUIRED`; use the separate [B14 recovery entry](recovery.md) before starting a new run.
3. Run QA01 against the native archives and previous manifest, then call E's FP1. A fingerprint matching the current successful batch returns `no_change` with its stored QA summaries. It creates no batch and leaves the pointer unchanged.
4. Load/register Raw and insert a fresh `running` batch in one transaction; commit it separately.
5. On the same connection, run C projection → A Vault → C Canonical → D dimensions/facts → B's QA02 and QA01/02 inserts → C QA → D QA → E publication.
6. Check that E published this candidate, with the same fingerprint/manifest and all seven valid QA summaries. B commits the build once.
7. Close the dedicated connection after outcome handling. The session lock spans registration, build and failure handling; closing the session releases it. This follows PostgreSQL's [session advisory-lock rules](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS).

E still derives and checks all required QA objects. B's summary check is a transport safeguard, not a replacement for E's gate. Official and synthetic pointers remain separate, while the session lock covers both.

## Results and failures

`RunResult.as_dict()` returns the result and run context; `exit_code` maps to the CLI exit status:

| Result | Exit | Meaning |
|---|---:|---|
| `succeeded` | 0 | Publication COMMIT was acknowledged. |
| `no_change` | 0 | The same input is already the current successful batch. |
| `busy` | 2 | Session lock unavailable; no new batch. |
| `failed` | 1 | Known failure with rollback; database failure logging may still need repair. |
| `unknown_commit` | 3 | Transaction outcome needs a database state check before retry. |

An exception from registration, publication or failure-record COMMIT returns `unknown_commit`. The runner does not retry or mark the candidate failed after a lost response. An unconfirmed rollback also stops with this unresolved result. These outcomes are not new `meta.batch.status` values.

[B14 recovery](recovery.md) reads the original run evidence and queries the same database through a new locked session. It preserves successful history and resolves only the selected batch. Its state tests use simulated replies; real recovery remains unverified.

Known failures save diagnostics, roll back the build and update only this candidate's `running` row in a separate transaction. Rolled-back QA passes are not reinserted. If failure logging is unavailable, file evidence remains and the unresolved database row needs inspection. Successful history is never updated by this path. Cleanup or receipt errors after acknowledged publication do not turn success into failure.

Evidence lives under `<evidence_root>/<dataset_kind>/runs/<run_id>/`: frozen manifest, registered bindings, QA reports/details, Raw counts, pre-COMMIT records, errors and final result. Pre-registration failures have no batch ID. Driver exception text is omitted because it can contain credentials; module diagnostics use explicit `IntakeError` details.

## Validation and remaining inputs

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

The initial suite recorded **380 passed, 10 skipped** on 2026-09-19, including 44 runner tests with scripted replies. The [original receipt](evidence/b10-b11-validation-2026-09-19.json) is unchanged. The [2026-09-20 run](input-qa.md#validation) passed 426 tests, including the eight B08 and two QA02 PostgreSQL tests. [B12's later checks](runner-locks.md) exercise real locks and early runner exits. Complete build transactions, concurrent builds and recovery remain unverified.

- **A:** remaining schema/loader grants and Vault callback. The B08 tables, PostgreSQL 16 environment and pinned driver have been verified locally.
- **C:** projection, Canonical and QA callbacks; accepted mappings and source reviews with the source owners.
- **D:** dimensions/facts and reconciliation QA callbacks.
- **E:** FP1 SQL/version and publication gate. Its existing QA protocol is already reused.

At the initial review, shared branches had no callable build/FP1/publication modules. JJ's later B08 environment supplies three tables; it does not supply these functions. Old reference SQL was not adopted. Full fault injection, concurrent builds, real recovery and end-to-end acceptance still need integration.
