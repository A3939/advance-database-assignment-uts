# D02 in the B package

D02 now installs with `arsia-native-intake`. It loads Source, Month and Severity dimensions and writes B's stage evidence. This is a D02-only integration; facts, the combined DW callback and a complete B10 build are still pending.

## Versions and paths

- B base: `bc4ed6b000a354babe3cab65e5b5028a41ae304a` (`peixian/dev`).
- D merge: `e4fbefa29fc275a39ac299af70bbf8e829cdee6d` (`yihua/D02`). The runtime matches validated implementation `dd98354319c654f7e44f87bf9d0df8af85a9451f` byte for byte.
- [PR #6](https://github.com/A3939/advance-database-assignment-uts/pull/6) was merged. Separately, `yyyZYH` submitted an [Approved review](https://github.com/A3939/advance-database-assignment-uts/pull/6#pullrequestreview-5303655984) of review head `306277bdf0b6a6fd9a0e97a2a6b207fba50d61fc`.
- Runtime: [`src/arsia_d02/`](../src/arsia_d02/). The two Python files were moved from `D02/src/arsia_d02/` without runtime edits.
- Package: `arsia-native-intake 0.1.0`, Python 3.12. Existing setuptools discovery includes both packages. D02 adds no external runtime dependency. Database checks use the existing `psycopg[binary]==3.3.6` pin.
- Binding version: `d02-0.1.0-e4fbefa`. [`config/d02-inventory.json`](../config/d02-inventory.json) records the real paths, dependencies and SHA256 values.

Keep future D02 changes coordinated with Role D. PR #6 holds the earlier review and detailed validation history.

## B interface

`s0_definitions("tests/fixtures/s0/contract.json")` supplies the existing sources, analysis years and severity definitions. The callback reads `context.manifest.as_dict()`, including `rules.severity`, and uses `context.batch_id` and `context.evidence`.

The installed entry point can be bound as follows:

```python
from arsia_d02 import runner_callback
from arsia_ingest.runner import ModuleBinding

d02 = ModuleBinding(
    runner_callback,
    "src/arsia_d02/dimensions.py",
    "d02-0.1.0-e4fbefa",
)
# D02 stage only. Call with B's ModuleConnection and RunContext.
counts = d02.callback(connection, context)
```

The caller registers valid source/batch records and owns the transaction. D02 does not commit, roll back or close the connection. It writes `d02-dimensions.json` through `RunEvidence` and translates contract errors to B's `IntakeError`.

The inventory fragment has `complete_dw: false`. Its `components.dw` list can seed the final DW inventory after D supplies D03 and the combined callback. Add their actual dependencies and recompute hashes then. Do not register this fragment as a finished DW implementation or treat it as a complete platform inventory. B09 and B10 still reject missing components.

## Reproduce

Run from this checkout with Python 3.12, Git and Docker on PATH. Use a new output directory for each database run.

```sh
python3.12 -m venv ../.venv-d02
../.venv-d02/bin/python -m pip install -r requirements-db.txt
../.venv-d02/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir ../d02-wheels
../.venv-d02/bin/python -m pip install --force-reinstall --no-deps ../d02-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
../.venv-d02/bin/python -I -c 'import arsia_d02, arsia_ingest; print(arsia_d02.__file__, arsia_ingest.__file__)'
../.venv-d02/bin/python -m pytest -q -o pythonpath= \
  tests/test_d02.py tests/test_manifest.py tests/test_runner.py \
  tests/test_fingerprint.py tests/test_s0.py

git fetch origin peixian/a-review-fixes
git worktree add --detach ../a-d02-schema c0824da06b6e7b3f73c4ddeab2114d10b7156913
../.venv-d02/bin/python tools/verify_d02_postgres.py \
  --a-root ../a-d02-schema --output ../d02-postgres-result
```

The database tool requires that exact, unchanged A checkout. It starts its own PostgreSQL 16 container, applies migrations 001–010 then 011, and logs in as `arsia_loader`. It keeps A03 grants unchanged and runs A's permission audit before and after the tests. The container uses a random loopback port and temporary storage, and is removed on exit. It never accepts a shared database URL. No database password is saved in the evidence.

Tests run against the installed wheel with pytest's source-path override disabled. The tool checks the installed D02 hash, records migration/test hashes and writes JUnit results, environment details, exact rows, callback evidence and cleanup status.

## Results and limits

The [receipt](evidence/b-d02-integration-2026-09-24.json) records this checkout's validation on 2026-09-24:

| Check | Result |
|---|---|
| Affected B regression, installed wheel | 192 passed, 0 skipped, 0 failed |
| D02 installed-package suite with PostgreSQL 16.15 | 34 passed, 0 skipped, 0 failed |
| Original A03 permission audit | Passed before and after |

The 34 cases comprise 6 definition/package/manifest checks, 27 real PostgreSQL cases and 1 complete-build preflight guard. The 6 checks also appear in the 192-test run; these totals overlap.

1. **Fixed S0 definitions:** B's real helper produces 3 sources, all 60 months in 2020–2024 and 12 source-specific severity rows. Every database field is checked, including unused categories and `__MISSING__`. Idempotency, content conflicts, foreign keys, denied operations, rollback and separate batch history pass. PostgreSQL and Python still sort `__MISSING__` differently; the merged fix handles that correctly.
2. **Real object and callback interface:** the actual `FrozenManifest` constructor, `ModuleBinding`, `ModuleConnection`, `RunContext` and `RunEvidence` pass against PostgreSQL. The test object contains real S0 inputs and partial inventory, including B's existing schema files. It is not a final platform freeze; the separate database setup uses all 11 A migrations.
3. **Final freeze and complete B10 build:** not completed. A real `run_build` call stops at `MANIFEST_VERSION_MISSING` before opening a database connection. Missing bindings also fail explicitly. No replacement FP1, empty callback, publication or release was used.

## Remaining handoff

- **D:** D03 fact loading, the combined dimensions/facts callback, reconciliation QA and their actual code inventory/version.
- **E:** real E03 FP1 SQL, signature, version and deployment evidence; E06 publication gate and binding.
- **A:** integrate the fixed schema and existing A06 Vault implementation/binding into the shared build checkout. The fixed A checkout was used here; it was not copied into B. PR #5's merge is separate from this validation.
- **C and source owners:** integrate the real projection, Canonical and QA bindings, accepted mappings and source-review records.
- **B:** assemble the real combined inventory, freeze it with B09, register all bindings and run full B10 once those inputs are present. Then validate QA persistence, publication and the remaining B12–B14 scenarios.

No new S0 source, month or severity material is needed from the user.
