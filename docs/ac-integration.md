# B integration: NSW projection, Vault and Canonical

B now installs the fixed A schema, A06, C03 NSW projection and C09 Canonical loader alongside D02. The verified path is native S0 input → Raw → NSW projection → Vault → Canonical. D02 runs on the same caller-owned transaction.

This is a component integration. Raw and dimensions cover all three S0 sources; projection and Canonical output cover NSW only. No FP1, full B10 build or publication is claimed.

## Inputs and changes

| Input | Pinned version |
|---|---|
| B base, after PR #8 | aff27d3f9bcaa5fcc0d84e9dcda4276b0fe7a636 |
| A, after PR #5 | a94314d5a53934cfae1e77f6aa9f6ca4a3f9b893 |
| A fix content | c0824da06b6e7b3f73c4ddeab2114d10b7156913 |
| C checkout | f5e26e2e81c56a8ec8fa0fc0f26341eeecb8e32c |
| C03 merge, PR #7 | cc39c6ffda18ea02ce1b393beaded1e5d6379176 |
| C09 merge, PR #9 | bec3b1a213938404571d656a187681684977a905 |
| D02 merge, PR #6 | e4fbefa29fc275a39ac299af70bbf8e829cdee6d |

PRs [#5](https://github.com/A3939/advance-database-assignment-uts/pull/5), [#7](https://github.com/A3939/advance-database-assignment-uts/pull/7) and [#9](https://github.com/A3939/advance-database-assignment-uts/pull/9) contain the upstream review history. Their merges are recorded here; this receipt does not assert separate Approved reviews.

- A migrations 001–011 and A06 are unchanged. B already had 001–003; this adds 004–011 and the original A03 permission audit.
- C09 and its validation helper are unchanged from the merged fix.
- C03 loads its nine SQL files through package resources. They moved into `src/arsia_c/projections/sql/` without SQL changes.
- B's three pinned VIC policy files now travel with the package. Definitions retain their exact hashes. External evidence stays in the checkout; `run_build` passes `project_root` to QA01 as its evidence root.
- No new Python dependency is needed. Use Python 3.12 and the existing database requirements.

The installed-wheel regression found both resource-path problems. Source-only tests had not exposed them.

## Runtime and inventory

| Stage | Callback | Code path |
|---|---|---|
| NSW projection | `arsia_c.projections.nsw:project` | `src/arsia_c/projections/nsw.py` |
| Vault | `arsia_ingest.vault_load:load_vault` | `src/arsia_ingest/vault_load.py` |
| Canonical | `arsia_c.canonical:load_canonical` | `src/arsia_c/canonical.py` |
| Dimensions | `arsia_d02.dimensions:runner_callback` | `src/arsia_d02/dimensions.py` |

[`config/ac-inventory.json`](../config/ac-inventory.json) records binding versions, dependencies, final paths and SHA256 values. Projection SQL belongs in code inventory; A's migrations belong in schema inventory. The fragment also hashes B's interface code and pinned policy resources.

`final_platform` remains false. C03 is not an all-source dispatcher, and D02 is not a complete DW callback. No default `BuildModules` registration was added. Tests resolve the four real `ModuleBinding` objects from this fragment.

B supplies `ModuleConnection`, `RunContext` and a separate `RunEvidence.for_stage(...)` directory to each callback. Modules do not commit, roll back or close B's connection. C09 rejects an already populated candidate; retry with a new batch. Repeated C03/D02 calls need fresh evidence directories because evidence files cannot be overwritten.

C03 still raises its upstream `ValueError` on semantic failures; B reports a failed stage and rolls back. This integration does not change those source rules or error semantics.

## Reproduce

From the checkout, with Python 3.12 and Docker available:

```sh
python3.12 -m venv ../.venv-b-ac
../.venv-b-ac/bin/python -m pip install -r requirements-db.txt
../.venv-b-ac/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir ../b-ac-wheels
../.venv-b-ac/bin/python -m pip install --force-reinstall --no-deps ../b-ac-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
AC_REQUIRE_INSTALLED=1 D02_REQUIRE_INSTALLED=1 \
  ../.venv-b-ac/bin/python -m pytest -q -o pythonpath= tests
../.venv-b-ac/bin/python tools/verify_ac_postgres.py --output ../b-ac-postgres-result
```

Unset `PYTHONPATH` and optional test DSNs before the default run. Its database/archive tests skip when their inputs are absent. Use a fresh output directory for the database command.

The verifier checks installed Python, SQL and policy bytes, then starts a private PostgreSQL 16.15 container with a random loopback port and temporary storage. It applies local migrations 001–011 and keeps A03 grants unchanged. Tests use `arsia_loader`; only setup and test cleanup use the owner. A database marker guards the committed-snapshot tests. The verifier removes the container and records final row counts. It does not accept a shared DSN.

## Validation

The [receipt](evidence/b-ac-integration-2026-09-24.json) records final results and input hashes.

| Final installed-package run | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Default B regression | 599 | 147 | 0 |
| Isolated PostgreSQL suite | 245 | 0 | 0 |

The PostgreSQL run includes database, unit and package checks. The two runs overlap. Default skips are database tests without DSNs, one D02 module collection, and three optional VIC/C06 checks; they are not passes.

The installed-package tests cover:

- B's real S0 reader, `s0_definitions`, `FrozenManifest`, bindings, connection facade, context and evidence writer.
- 19 unchanged Raw rows → 2 NSW crashes, 3 real units and 1 eligible map point. All 24/11 fields match the typed projection after Vault and Canonical loading.
- Exact business keys and lineage, missing values, false eligibility, decimal coordinates and structured reasons. Upstream C09 tests also preserve known zero and reject coercion.
- All 3 sources, 60 months and 12 severity definitions in D02, including `__MISSING__`.
- 16 real QA01/QA02 result rows: every persisted field is compared with B's reports. These are S0 input checks, not C/D QA or E's publication gate.
- Repeat rules, changed analysis years, caller rollback, downstream failure, and preservation of a committed test snapshot. These test snapshots are not published releases.
- B09/B10 rejection of the partial inventory and missing real callbacks before connection/publication.

The real `FrozenManifest` object includes actual files and hashes but only partial component inventory. Constructing it validates the interface; it does not complete the final platform freeze. Existing upstream fixture contexts remain labelled component tests; the new B chain tests use genuine B objects.

## Remaining work

- **C:** C04 VIC, C05 QLD, the all-source projection dispatcher, C10 persisted QA and source-rule alignment. The final remote check at `e2a897ae41c11ec1a0c4051becfe71f9c475e66c` adds C04 relationship SQL and C11 notes. C04 Python, insertion SQL and its test are still empty; C05/C10 are not implemented. C03/C09 bytes are unchanged. Existing C06/C07 remain separate components.
- **D:** D03 facts, the combined DW callback and reconciliation QA.
- **E:** real E03 FP1 SQL/signature/version/deployment evidence, E06 publication and analysis inventory.
- **B with module owners:** assemble the complete actual inventory, freeze it and run full B10. Then validate publication, no-change, concurrent builds, failure handling and recovery with the real modules.

No new S0 source, month or severity material is needed. Official-data acceptance, website status and other roles' branches are outside this delivery.
