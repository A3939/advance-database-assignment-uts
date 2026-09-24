# D02 PostgreSQL integration review

D02 loads the S0 dimensions under A's unchanged `arsia_loader` permissions on
PostgreSQL 16.15. One implementation defect was found and fixed: database locale
ordering caused correct severity rows to fail exact-content verification.
This delivery covers the dimension stage, not D03 or complete platform acceptance.

## Fixed inputs and result

| Input | Commit / environment |
|---|---|
| D02 upstream | `5d871e58100348b8cfb7dd11e3978bb233652efc`, `yihua/D02` |
| A fixed database | `c0824da06b6e7b3f73c4ddeab2114d10b7156913`, `peixian/a-review-fixes` |
| A06 ancestor | `d30405eab42ffb2475dea9f7322e7b803b879963` |
| B | `bc4ed6b000a354babe3cab65e5b5028a41ae304a`, `peixian/dev` |
| Database | PostgreSQL 16.15, UTF8, UTC, `en_US.utf8` collation |
| Python / driver | Python 3.12.6, psycopg 3.3.6 |

A PR #5 was open and JJ (`LALAJJ0302`) had approved `c0824da` when checked on
2026-09-24. Validation used that fixed commit directly; it does not depend on
the PR being merged. All migrations 001–010 and `011_review_validation_fixes.sql`
were applied in order. Full A, B and D Git checkouts were used for the final run.
The older A review artifact directory was used only as an initial migration
reference, and all 11 SQL files were verified against the fixed Git checkout.

The same 36-case suite produced **20 passed / 16 failed** on the upstream D02
implementation and **36 passed / 0 skipped / 0 failed** after the fix:

- 7 original tests use FakeDatabase; they are not PostgreSQL evidence.
- 27 new cases exercise real PostgreSQL connections, including a real login as
  `arsia_loader` (both `current_user` and `session_user`).
- 2 new cases check that incomplete full-platform freezing/building is rejected.

The final run provisions a new loopback-only container and private tmpfs cluster,
then removes it. It never uses a shared database. A03's original role audit passes
before and after testing: 17 migrator-owned tables, no loader DELETE permission,
no reader access to base tables, and 7 reader views. No grants were expanded.

## Defect and minimal fix

With `en_US.utf8`, PostgreSQL orders `F, I, __MISSING__, N`; Python orders
`F, I, N, __MISSING__`. `_verify()` previously compared tuples in those different
orders, raising `D02_DATABASE_MISMATCH` even though all 12 stored rows were right.
The FakeDatabase tests use Python sorting, so they did not expose this.

The fix sorts fetched Source and Severity rows by the same Python identity keys
used for the expected rows. Every field and the entire row set are still compared.
No SQL constraint, permission, missing category, or transaction rule is relaxed.
The batch-local dimensions and shared month dimension retain their existing keys.
`is_fatal_crash` remains a manifest semantic field; A's severity dimension has no
such column, and D03 must populate the fact-level flag from Canonical.

## What the database tests establish

- B's actual `s0_definitions()` produces 3 sources, all 60 months in 2020–2024,
  and 12 source-specific definitions including every `__MISSING__` category.
  Each stored dimension field is checked against B's definitions independently
  of the D02 row builder. No observed fact rows are needed to create categories.
- Repeated calls preserve the same rows. Changes to all seven non-key Source /
  Severity payload fields are rejected. An unexpected extra category is rejected.
- Missing batch, missing source, and missing composite severity parent fail with
  actual PostgreSQL foreign-key violations.
- Loader UPDATE on all three dimensions, DELETE, TRUNCATE, DDL, and switching to
  `arsia_migrator` fail with actual permission errors.
- Another connection cannot see uncommitted writes. Caller rollback removes all
  three dimension writes and the test batch. D02 never commits, rolls back, closes,
  or changes the connection's autocommit setting.
- A second batch can carry revised labels and definitions without changing the
  first batch. This is checked both within a transaction and after explicit caller
  commits using a separate observer connection.
- The genuine B `ModuleConnection`, `RunContext`, `RunEvidence`, and `IntakeError`
  interfaces work. The callback writes the right batch/count evidence, and B's
  evidence writer produces a verified SHA256 reference. Conflicts are translated
  to `IntakeError` and do not produce success evidence.

Test batch fingerprints are explicitly labelled test identifiers, not E's FP1.
No batch is published. The final tables and current-release pointer are empty.
Committed-history test cleanup uses the isolated test administrator; the module
and all loader operations retain the production permission model.

## Three validation layers

| Layer | Actual result |
|---|---|
| Fixed S0 definitions | Passed using B's real generator, with exact 3/60/12 PostgreSQL content. |
| Real FrozenManifest object / callback interface | Passed using the actual `arsia_ingest.manifest.FrozenManifest` constructor, including its full schema validation and immutable copy behavior. Native S0 preparation supplies real file metadata; code/schema entries hash actual available bytes. No FakeFrozen class or monkeypatch is used. |
| Final B09 freeze and complete B10 build | **Not completed.** The interface-test object contains only the available code inventory. `freeze_manifest()` correctly rejects the incomplete component inventory; an actual `run_build()` call stops at preflight with `MANIFEST_VERSION_MISSING`, before opening a DB connection. This is a dependency-guard test, not a successful build. |

The constructor-level object is an interface-test snapshot. It is **not** the
final, inventory-verified platform FrozenManifest. Missing components are never
filled with placeholder SQL, another component's code, invented hashes, or a fake FP1.

## B09 / B10 handoff and remaining owners

The [inventory fragment](../integration/dw-inventory-fragment.json) records actual
paths and hashes for `D02/src/arsia_d02/__init__.py`,
`D02/src/arsia_d02/dimensions.py`, and `D02/pyproject.toml`. Merge these paths into
`inventory.components.dw` only when assembling the real platform inventory.
Runtime D02 uses the Python standard library; the B callback additionally uses
B's error/context/evidence interfaces. Psycopg is owned by the caller connection.
The pinned development requirements are only for reproducing this review.

For the dimension stage, B's actual binding signature is:

```python
ModuleBinding(
    callback=arsia_d02.dimensions.runner_callback,
    code_path="D02/src/arsia_d02/dimensions.py",
    version="<reviewed D02 delivery commit>",
)
```

That binding is D02-only. It must not be registered as a complete warehouse
implementation until Role D provides D03 and a combined callback that invokes
D02 then D03 on the same connection and transaction.

| Owner | Remaining delivery |
|---|---|
| Role D | Review this fix/tests; provide D03, the combined DW callback, and its actual code paths/version; supply the real D QA binding for full integration. |
| Role E | Supply real E03 FP1 SQL/operation, E06 publication implementation, and their actual inventory paths/versions. |
| A / C / D / E with B | Confirm and register the actual project, vault, canonical, QA and publication callbacks and full code/schema inventory. A06's `arsia_ingest.vault_load.load_vault` is present in the fixed A checkout; it was not replaced or claimed absent. |
| B | Assemble the final inventory-verified FrozenManifest once those modules are available, compose all bindings, and run the complete build/QA/publication acceptance. |

No additional S0 source, month, severity, or fixture material is needed from Peixian.
This review does not change website acceptance statuses or merge Role D's branch.

## Reproduce

Use Python 3.12, Docker, Git and Git LFS. Keep the checkouts separate. From the
repository root, after checking out this review branch:

```sh
git fetch origin yihua/D02 peixian/a-review-fixes peixian/dev
GIT_LFS_SKIP_SMUDGE=1 git worktree add --detach ../d02-a c0824da06b6e7b3f73c4ddeab2114d10b7156913
GIT_LFS_SKIP_SMUDGE=1 git worktree add --detach ../d02-b bc4ed6b000a354babe3cab65e5b5028a41ae304a
python3.12 -m venv ../d02-test-venv
../d02-test-venv/bin/python -m pip install -r D02/requirements-dev.txt
../d02-test-venv/bin/python D02/tools/verify_postgres.py \
  --a-root ../d02-a --b-root ../d02-b --output ../d02-postgres-result
```

The output directory must be new. The script pins the actual PostgreSQL image
digest, verifies A/B commits and unchanged tracked inputs, applies all migrations,
runs the original A03 audit plus the 36-case suite, records hashes/results, and
removes its own container even on test failure. It does not accept an external DSN.
To reproduce the failing baseline, use a separate D worktree at `5d871e5`, copy
only `D02/integration/`, `D02/tools/verify_postgres.py` and the test requirements
from this review, leave `dimensions.py` unchanged, and run the same command.

Evidence is indexed in [the review receipt](../evidence/postgres-review/receipt.json).
