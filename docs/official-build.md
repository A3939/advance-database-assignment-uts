# B: pinned official build

This B version connects the seven pinned NSW, restricted VIC and QLD files to
A/C/D/E's installed callbacks, B's `FrozenManifest`, E03 SQL FP1 and E06 publication.
Analysis covers 2020–2024; all 2,118,028 original rows remain in Raw. D09 is deferred.

## Inputs and ownership

| Component | Pinned version |
| --- | --- |
| B baseline, PR #34 | `c8772ba6205be7830e191ba101997fa56aff2532` |
| A migrations/A06 | `c0824da06b6e7b3f73c4ddeab2114d10b7156913` |
| A04 NSW contract | `46aa1e149738c64502632c65bd38fd33b96d4625` |
| C baseline | `6987e604bb93809aa94a736085c3e8320452461d` |
| D02–D08 baseline | `d57c3f4ff2fb57eb84ebc414ef77911073c0de06` |
| E03/E06 baseline | `aec3b4692382e48ea4f778f04a31a4ca5ba5fa57` |

A/C/D/E keep authorship of their modules. Peixian added admission, integration,
reader limits and the fixes below. The receipt identifies the exact tested B
commit and file hashes.

`config/native-inputs.json` and `config/official-inputs-v1.json` pin input bytes,
origins and evidence. `config/build-inventory.json` records installed code and
migrations. VIC retains its four-file policy, registered cases and unresolved
definitions; full-source confirmation remains false.

B adapts A's NSW mapping IDs and declared-unit field to the shared manifest and
C10/E06 formats, retaining their original values. A's contract and evidence stay
unchanged. The original C-review field remains null; B's review is recorded
separately. `config/official-expected-results-v1.json` contains earlier native
observations with evidence hashes. E's independent acceptance remains separate.

## NSW query fix

C03 now stages complete selected NSW files in loader-owned temporary tables.
Non-unique native-key indexes and local statistics prevent slow relationship
joins. Raw IDs, values, excluded years and invalid keys remain available to the
same checks. No permanent schema, grant or business rule changed.

## C09 parent lookup

C09 now keeps all four Unit-to-Crash parent keys inside one bounded lateral
lookup. Missing and wrong parents still fail. A fresh 1,001-crash/2,001-unit
regression checks the executed plan and caller rollback. C owns the original
Canonical implementation; B added the performance repair.

## C06 full-file lookup

C06 stages all selected Accident, Vehicle and Person rows in a loader-owned
temporary table, with a non-unique native-key index and local statistics. The
checks retain Person rules, registered cases, count checks and output fields.
Tests compare original and revised outputs in normal and restricted modes.
Use the existing Python review entry points; the packaged SQL now expects their
temporary-table preparation. C owns the original Person implementation.

## D04 parent contract compatibility

The frozen VIC Node contract omits `parent_fields`. D04 now resolves that short
form only from one selected same-source Crash resource with the exact ordered
key. Explicit null, empty, mismatched or ambiguous declarations still fail.
B added compatibility tests; D owns reconciliation. VIC policy bytes stay unchanged.

## D08 first-read query fix

The first full NSW unit report spent over eight minutes in its parent lookup.
That reader query was cancelled after the build had published successfully, so
that suite is retained as diagnostic evidence. D08 now reads eligible parents
and units once, combines them with `UNION ALL`,
and checks parent presence with a window over the four-part key. It counts units
before joining source labels. Date filters, unit rules and reader grants remain
unchanged. Focused validation passed 46 checks, including 28 PostgreSQL cases.
The final full-snapshot run is pending. D owns the original report; B adds the
repair and installed-reader checks.

## Run

From the checkout, use Python 3.12 and Docker:

```sh
python3.12 -m venv ../official-venv
../official-venv/bin/python -m pip install -r requirements-db.txt
../official-venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w ../official-wheel
../official-venv/bin/python -m pip install --force-reinstall --no-deps ../official-wheel/arsia_native_intake-0.1.0-py3-none-any.whl
../official-venv/bin/python tools/verify_official_build_postgres.py \
  --native-root /absolute/path/to/raw_datasource \
  --archive-root /absolute/path/to/intake \
  --output /absolute/path/to/new-validation-directory
```

Use a new output directory. Optional `--prepared-run /absolute/path/to/intake/official/runs/RUN_ID`
reuses a complete preparation while checking its archived records and all seven
original hashes. New bytes need reviewed definitions and evidence.

The verifier applies unchanged A migrations 001–011 to private PostgreSQL 16.15.
It checks original A03 permissions before and after, uses real `arsia_loader`
logins, then removes the container and its image volume. Storage uses the
container's writable layer. Shared databases and public releases are untouched.

Run focused regressions in separate fresh databases with the same installed
Python and a new `--output` directory for each helper:

- `tools/verify_nsw_cold_plan_postgres.py`
- `tools/verify_c09_cold_plan_postgres.py`
- `tools/verify_c06_cold_plan_postgres.py`
- `tools/verify_d04_lineage_postgres.py`
- `tools/verify_d08_cold_plan_postgres.py`

For application code, prepare with `arsia_ingest.official.prepare_official_inputs()`;
pass its `run_dir` to `arsia_ingest.build.official_request()`, then call
`arsia_ingest.runner.run_build(**request)`. Supply a fresh loader connection.
The runner owns commits, rollbacks and the shared lock.

Rolled-back fixtures and autovacuum previously left misleading Raw statistics,
causing a source-wide foreign-key scan. Keep full and focused suites separate.
For a reused database, A/the owner should check statistics after import commits
and run `ANALYZE raw.record` when needed. B adds no loader maintenance grants,
session planner overrides or runtime waits.

## Reader and acceptance boundary

`arsia_ingest.official_reader.query_official()` takes a reader connection, a
successful `batch_id`, one `source_id`, and a report: `trend`, `severity`, `units`
or `map`. It validates the pinned batch through D's installed queries and returns
source labels, quality limits and coverage. Results remain source-specific.
NSW unit reports are available; VIC/QLD units and all official maps return
`status="unavailable"`, a reason and `rows=None`.

**Results pending:** insert the completed full-run outcome and exact test totals
from [the validation receipt](evidence/official-build-validation-2026-09-27.json).
The tests cover actual publication, injected rollback, preserved S0 history,
official retry, `no_change`, seven QA groups and native-count comparisons.

C reviews B's C03/C06/C09 repairs; D reviews the D04 compatibility fix, D08 reader repair and later
D09 interface use. E owns independent acceptance. A/E and the team confirm the
four [E01 course decisions](e/e01-course-decisions.md). B then freezes the expanded
inventory and repeats affected checks. `final_platform` remains false.
