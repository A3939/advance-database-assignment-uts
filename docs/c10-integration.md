# C10 in B

B now installs C10 and returns its real `qa_c` binding from `arsia_ingest.components.bindings()`. C10 runs QA03/04/05/07 against the current batch and writes results through B's `QAReport`, database writer and stage evidence directory. B still owns the transaction.

## Versions and ownership

| Input | Commit |
|---|---|
| B base | `b51dc2860f50feb9ea52d4336f7bfaa1db5471fb` |
| Checked C branch after PR #28 | `6987e604bb93809aa94a736085c3e8320452461d` |
| C10 implementation from merged [PR #26](https://github.com/A3939/advance-database-assignment-uts/pull/26) | `3f6c94795ee0fc8ec0f17903f23fd4a85b5646ac` |
| QA07 fix merged in [PR #28](https://github.com/A3939/advance-database-assignment-uts/pull/28) | `975d8b6` (range), `c3fbbd4` (Raw attribution) |
| A schema | `c0824da06b6e7b3f73c4ddeab2114d10b7156913`, migrations 001–011 |

Role C wrote the original C10 in [7bfb08e](https://github.com/A3939/advance-database-assignment-uts/commit/7bfb08ee4b3b0740e554ae89c6286c39db17ead2), [ba65982](https://github.com/A3939/advance-database-assignment-uts/commit/ba659821e3c60dcd5629fcc3dacd9acf1c9239a0) and [b0626ea](https://github.com/A3939/advance-database-assignment-uts/commit/b0626ea552de6c42835cc4b6497ef6662c2d7715), and C06 in [c816f5b](https://github.com/A3939/advance-database-assignment-uts/commit/c816f5b48ffe0afccc8d6702b9b2b208073eeeb9). Peixian added the C10 implementation and validation in PR #26. This delivery imports that merged code into B, adapts the binding and inventory, and checks the installed interfaces. The QA07 fixes are included as cherry-picks `02ee910` from `975d8b6` and `e13b10a` from `c3fbbd4`, preserving both original commit references. PR #28 is now merged into `yue/role-c` at `6987e604bb93809aa94a736085c3e8320452461d`. All 14 imported C10/C06 files match that merge.

## Installation and binding

```python
from arsia_ingest.components import bindings
from arsia_ingest.runner import BuildModules

modules = BuildModules(**bindings())
# modules.qa_c is available. modules.publish is still None.
```

- Callback: `arsia_c.qa:runner_callback`; path: `src/arsia_c/qa.py`; version: `c10-role-c-v1.2`.
- Supporting code: `qa_expectations.py`, `person_checks.py` and `restricted_person.py` in `src/arsia_c/`.
- Resources: five `c10_*.sql` files plus `c06_vic_person_checks.sql` under `src/arsia_c/sql/`; C06 and VIC policies under `src/arsia_c/config/`.
- Existing package-data rules include these resources. No new external dependency is needed.
- [`cd-inventory.json`](../config/cd-inventory.json) records 77 code/dependency files and 11 schema files. Both C10 and D04 belong to its `qa` component. All 14 C10/C06 input files match the checked C merge. Two existing VIC policy files were reused unchanged.

Pass B's `ModuleConnection` and `RunContext`, with a real `FrozenManifest` and `context.evidence.for_stage("qa_c")`. The persisted running batch must match the context. C10 refuses duplicate results. It raises `C10_BLOCK` after writing diagnostics when it finds a blocking difference; the caller rolls back database writes while keeping file evidence.

## Reproduce

Use Python 3.12 and Docker from this checkout. Unset `PYTHONPATH` and optional test DSNs. Keep the venv outside the checkout and use a fresh output directory.

```sh
python3.12 -m venv ../c10-venv
../c10-venv/bin/python -m pip install -r requirements-db.txt
../c10-venv/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir ../c10-wheels
../c10-venv/bin/python -m pip install --no-deps ../c10-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
AC_REQUIRE_INSTALLED=1 CD_REQUIRE_INSTALLED=1 D02_REQUIRE_INSTALLED=1 \
  ../c10-venv/bin/python -m pytest -q -o pythonpath= tests
../c10-venv/bin/python tools/verify_c10_integration_postgres.py --output ../c10-postgres
```

The wheel regression also builds a separate wheel, installs it into a clean venv, deletes the build source and loads SQL with `python -I` outside the checkout. It checks installed hashes and the actual B binding.

## Results and limits

The [validation receipt](evidence/c10-year-coverage-2026-09-25.json) records the fixed version, hashes and local evidence before PR #28 merged. Its PR status and remaining-work fields are historical. The [merge check](evidence/c10-merge-check-2026-09-25.json) records the metadata update and confirms unchanged runtime, migration and resource hashes. The [initial integration receipt](evidence/c10-integration-2026-09-25.json) retains the earlier v1 results.

| Run | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Installed default regression, including clean-wheel test | 734 | 330 | 0 |
| Focused PostgreSQL/interface regression | 84 | 0 | 0 |

The second run contains 21 C10 database tests (5 interface and 16 year-coverage cases), 6 existing C/D database tests, 1 full-build preflight check, 4 inventory checks and 52 runner unit tests. These totals overlap with the default run. Default skips need a database or optional official archives.

S0 uses B's real definitions: 3 sources, 60 months and 12 severity definitions, including `__MISSING__`. C10 wrote 27 object results and 4 summaries. Two location objects remained `limited`, as expected. The tests checked context rejection, repeat-call rejection, blocking evidence, append-only grants and caller rollback. They used PostgreSQL 16.15, unchanged A03 `arsia_loader` permissions and byte-matched A migrations. All 17 persistent tables were empty after cleanup; the private container was removed.

The test manifest is a real `FrozenManifest` with a **partial** inventory. It is not the final platform freeze. Official VIC/QLD archives were not replayed in this delivery; earlier C10 evidence remains in PR #26.

The year regression first recorded 71 passes and 7 failures: QA07 omitted extra 2019/2025 rows, although QA05 already blocked those cases. The patch adds located QA07 blocks and retains legal boundaries, complete Raw and other-batch history. This does not demonstrate a former full C10 bypass. Six further cases reproduced invalid Raw being counted in every year. These now appear once in their native year or one blocking `unknown_year:<source_id>` diagnostic; unrelated empty years stay clear.

Next work:

- **B with C/D:** extend the [passed S0 QA01–QA07 joint checks](qa-joint-validation.md) to agreed official scopes. The QA07 fixes are merged into C through PR #28.
- **E:** supply corrected, database-tested FP1 and publication code with their real inventory entries.
- **B and module owners:** assemble the final inventory, including D's analysis/query code, then run complete B10 acceptance.

`final_platform` remains false. No publication or full-platform acceptance is claimed. No new S0 materials are needed.
