# Three-source C/D integration in B

B now provides the real bindings for NSW, VIC and QLD projection, A06 Vault, C09 Canonical, D02/D03 DW and D04 QA06. The loader uses B's connection, context and evidence writer. It never supplies placeholder C10 or E callbacks.

## Versions and ownership

| Input | Commit |
|---|---|
| B base | `60cb7fea76ece5af9a9e32a3f0a7acf11246b951` |
| C | `ad8baeddd3f6d2eeccdc2e31bafd71b687ad4da8` |
| D | `337101f68079ed666701c43f387a5df1c526ed4a` |
| A fixed schema and A06 | `c0824da06b6e7b3f73c4ddeab2114d10b7156913` |

C owns the projections, C07 location logic and C09 validation. D owns D02/D03 and D04. A owns the schema and Vault loader. B adds installation support, the dispatcher, bindings, inventory and integration tests. The existing B fix that loads C03 SQL from package resources is retained.

## Runtime

Use `arsia_ingest.components.bindings()` for the available `ModuleBinding` objects:

| Stage | Callback |
|---|---|
| project | `arsia_c.projections.dispatcher:project` |
| vault | `arsia_ingest.vault_load:load_vault` |
| canonical | `arsia_c.canonical:load_canonical` |
| dw | `arsia_d03.facts:runner_callback` (D02 + D03) |
| qa_d | `arsia_d04.reconciliation:runner_callback` |

The Python files are under the matching `src/` packages. C04/C05/C07 resources are in `src/arsia_c/sql/` and `src/arsia_c/config/`. C03 keeps its SQL in `src/arsia_c/projections/sql/`. No new Python dependency is needed.

[`config/cd-inventory.json`](../config/cd-inventory.json) lists the exact paths, versions, dependencies and hashes. Its `qa` component contains D04 only, and `final_platform` stays false. The old AC inventory remains a supported NSW-only subset. Neither fragment is the final platform inventory.

The dispatcher selects one source per supported jurisdiction before writing. The callbacks share B's transaction. Repeated projection/DW calls use a fresh evidence directory. Canonical rejects a populated candidate, and QA rows are append-only; retries must follow those contracts.

## Reproduce

From the checkout, using Python 3.12 and Docker:

```sh
python3.12 -m venv ../.venv-b-cd
../.venv-b-cd/bin/python -m pip install -r requirements-db.txt
../.venv-b-cd/bin/python -m pip wheel --no-deps --no-build-isolation . --wheel-dir ../b-cd-wheels
../.venv-b-cd/bin/python -m pip install --force-reinstall --no-deps ../b-cd-wheels/arsia_native_intake-0.1.0-py3-none-any.whl
AC_REQUIRE_INSTALLED=1 CD_REQUIRE_INSTALLED=1 D02_REQUIRE_INSTALLED=1 \
  ../.venv-b-cd/bin/python -m pytest -q -o pythonpath= tests
../.venv-b-cd/bin/python tools/verify_cd_postgres.py --output ../b-cd-postgres-result
```

Unset `PYTHONPATH` and optional test DSNs for the default run. Use a fresh database output directory. The verifier checks installed bytes, starts a private PostgreSQL 16.15 container on a random loopback port, applies A migrations 001–011 and audits A03 permissions before and after. Application calls use `arsia_loader`. Owner access is limited to setup, labelled fault injection and cleanup. The container is removed after the run.

## Acceptance boundary

The new B chain uses the real S0 generator, `FrozenManifest` constructor, `ModuleBinding`, `ModuleConnection`, `RunContext` and `RunEvidence`. Its manifest contains actual file hashes and a partial component inventory. It is an interface test object, not a final platform freeze or E FP1 result.

S0 expectations are 19 Raw rows, 6 crashes, 6 real units, 3/60/12 dimensions, 6 facts, 16 QA01/QA02 rows and 16 QA06 rows. QLD aggregate unit counts stay in Raw. Missing severity stays `__MISSING__`; absent categories and months remain in the dimensions. Tests also cover exact field transfer, analysis-year filtering, retry rules, conflicting definitions, transaction rollback and old-batch preservation.

Committed history fixtures stay explicitly unpublished. These tests do not validate official-data publication. Existing VIC restrictions remain in place.

## Next inputs

- **C:** complete C10 `qa_c`, with all required QA03/QA04/QA05/QA07 objects, summaries and persistence.
- **E:** corrected and database-tested E03 FP1 and E06 publication, plus their real code/schema inventory and acceptance inputs.
- **B with C/D/E:** freeze the complete inventory, then run full B10 success, no-change, failure, concurrency, publication and recovery acceptance.
- **D/B:** integrate D05–D08 query interfaces and reader permissions separately. They are outside this loading-stage delivery.

No new S0 definitions are needed.

## Local validation

The [receipt](evidence/b-cd-integration-2026-09-25.json) records versions, file hashes and evidence locations.

| Installed-package run | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Default regression | 725 | 270 | 0 |
| PostgreSQL-enabled regression | 602 | 0 | 0 |

These suites overlap. The PostgreSQL-enabled run includes unit and packaging checks. The default skips require a database or optional official archives. Seven new database integration cases use B's actual interfaces; imported component tests retain their original fixtures.

All eleven migrations match A's fixed commit byte for byte. The original A03 audit passed before and after. All 17 tables were empty after cleanup and the private container was removed. The initial suite passed; the later [D04 lineage review](d04-lineage-review.md) confirms six same-file wrong-row cases that QA06 misses. PR18 still needs D's fix and B's integration rerun. B's work covers the dispatcher, package integration, bindings, inventory and validation.

Full local logs are under `artifacts/role-b-next-20260925/cd-postgres-3/` in the course workspace.
