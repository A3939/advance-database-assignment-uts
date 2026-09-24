# C03 — NSW projection

C03 produces the complete 24-field `pg_temp.arsia_i_crash` and 11-field
`pg_temp.arsia_i_unit` rowsets inside B's transaction. It does not commit,
roll back, calculate FP1, load Satellites/Canonical, or publish a release.

## Invocation

```python
from arsia_c.projections.nsw import project
from arsia_ingest.runner import ModuleBinding

nsw_binding = ModuleBinding(
    callback=project,
    code_path="src/arsia_c/projections/nsw.py",
    version="c03-nsw-v2",
)
# Within the team's project-stage dispatcher:
project(shared_connection, context)
```

The caller supplies B09's `context.manifest.as_dict()`, the current `batch_id`
and B10 evidence writer. Select one NSW source and exactly one `crash` and
one `traffic_unit` input by their declared roles. Resource IDs are not fixed.
Add the Python entry point and every SQL file it reads to the real build
inventory; `code_path` alone does not freeze the SQL dependencies.

| Input/rule | Behaviour |
|---|---|
| Files and identity | Exact source/resource/hash/parser selection; require the declared full Raw row count and matching release/parent identities. |
| Keys | Use A05's encoder. Reject blank/Unicode-whitespace keys, duplicates and orphans across the complete snapshot **before** filtering years. Valid ID text is unchanged. |
| Years | Use inclusive `manifest.analysis.year_from/year_to`, not a literal interval. Native occurrence years satisfy A02's 1900–2100 constraint. |
| Severity | Use source/version-specific `rules.severity`. S0/S8 use their declared direct codes. An explicit `native_severity_codes` mapping can map native text to those codes. The A04 `nsw-crash-projection-v1` adapter uses its declared English labels. Unknown nonempty values block. |
| Units | Use `unit_types` from the unit mapping. For A04's official shape, explicitly declared `semantics.unit_type_groups` are retained as source-specific codes. Missing types retain the unit with false eligibility and structured reasons. |
| Counts | Validate nonnegative integers before conversion. A missing required casualty component gives NULL, never a zero-filled sum. Known totals must fit the target integer type. |
| Locations | S0's declared EPSG:4326 coordinates are checked before rounding, with the crash Raw row as lineage. Missing/invalid/unconfirmed locations retain the crash. The first official profile always clears coordinates, CRS and location lineage, with `crs_unconfirmed`. |
| Shared rowsets | Preserve other sources/batches/releases. Repeating C03 replaces only its exact batch/source/release rows. New temporary tables expire at commit. |
| Evidence | Write `c03-nsw-projection-counts.json`, including projected/Raw/excluded counts, eligible metrics, missing unit types and analysis years. Unknown totals stay NULL. |

S0 missing tokens are native NULL and empty string. The A04 v1 official adapter
uses native NULL. Different fields, tokens or CRS operations require an explicit
adapter change; do not silently reinterpret a changed definition. Draft official
contracts are rejected. This implementation does not confer source approval.

The standalone `c03_nsw.sql`, `c03_nsw_traffic_unit.sql` and
`c03_nsw_crash_projection.sql` are inspection queries, not the complete callback.
Use `project` for validation and complete C01 output.

## Reproduce the checks

Use Python 3.12 and a disposable PostgreSQL 16 database migrated with A's
001–011 scripts. The tested A revision is
[`c0824da`](https://github.com/A3939/advance-database-assignment-uts/tree/c0824da06b6e7b3f73c4ddeab2114d10b7156913),
including the fixes in [PR #5](https://github.com/A3939/advance-database-assignment-uts/pull/5).
Use `arsia_loader`, not a superuser, and the team's UTC/UTF-8 settings.
The tests install no migrations and roll back their database writes.

```sh
python -m pip install -r requirements-dev.txt 'psycopg[binary]==3.3.6'
# Set ARSIA_TEST_DSN to that disposable database's arsia_loader connection.
python -m pytest -q tests/test_c03_nsw_projection.py tests/test_c03_nsw_postgres.py
```

Without `ARSIA_TEST_DSN`, PostgreSQL tests skip. A configured but unusable
connection fails. A skipped run is not database-validation evidence.

Recorded result: **67 passed, 0 skipped, 0 failed** (25 unit cases and 42
PostgreSQL cases). The related S0, Raw loading and manifest suite passed **201**
cases. C03 also passed all 67 cases using B's `peixian/dev` revision `bc4ed6b`.
See [the validation receipt](c03-validation-2026-09-24.json).

The S0 integration test uses B's actual native reader, B08 loader, B09
`s0_definitions`, B10 `ModuleConnection`/`RunEvidence`, and A's installed
Canonical CHECK constraints. It verifies 2 NSW crashes, 3 real units and 1
eligible map point, unchanged Raw payloads, real Raw lineage and caller rollback.
Its component snapshot deliberately has no invented full build inventory or FP1.
Copying Canonical CHECK constraints into temporary validation tables does not
claim that A06 or C09 was executed. Full inventory freezing, C10 QA persistence,
Satellite/Canonical loading and publication acceptance remain separate integration
steps. No official production-data or full-project acceptance is claimed here.
