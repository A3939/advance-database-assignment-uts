# B: pinned official build

B connects the existing NSW, restricted VIC and QLD files to the same runner
used by S0 and S8. The entry uses actual A/C/D/E callbacks, a `FrozenManifest`,
E03 SQL FP1 and E06 publication. D09 is deferred.

## Inputs and ownership

- B base: `c8772ba6205be7830e191ba101997fa56aff2532` (PR #34).
- A migrations/A06: `c0824da06b6e7b3f73c4ddeab2114d10b7156913`, migrations 001–011.
- A04 NSW contract: `46aa1e149738c64502632c65bd38fd33b96d4625`.
- C: `6987e604bb93809aa94a736085c3e8320452461d`.
- D02–D08: `d57c3f4ff2fb57eb84ebc414ef77911073c0de06`.
- E03/E06: `aec3b4692382e48ea4f778f04a31a4ca5ba5fa57`, with the reviewed B fixes.

A/C/D/E retain authorship of their modules. Peixian added the official entry,
admission adapter, read boundary and integration checks. A's original NSW
contract and evidence are copied unchanged. B adapts its mapping IDs to the
shared manifest syntax and retains the original IDs. The NSW declared-unit field
is adapted to the existing C10/E06 object format using A's explicit resource and
parent rules; its original string is retained. The original C-review
field remains null; B's assisted integration check is recorded separately.

The seven files contain 2,118,028 native rows. Analysis covers occurrence years
2020–2024. Out-of-range rows stay in Raw. File hashes, origins, source definitions
and evidence pins are in `config/native-inputs.json`,
`config/official-inputs-v1.json` and the frozen manifest. VIC keeps its exact
four-file policy, known cases and unresolved definitions. Its full-source
confirmation flags remain false, and no unrestricted VIC review is supplied.

`config/official-expected-results-v1.json` records earlier independent native
observations for comparison. Their receipts are retained with hashes. These
expectations are B's regression inputs, not E's independent acceptance.
The September 23 source-decision guide and review index are retained unchanged
for their recorded hashes. Their implementation status is historical; use this
page and its validation receipt for the current build.

## NSW query fix

The first full run exposed slow NSW joins just after initial Raw loading. A
relationship query replanned against updated statistics finished in 0.57 seconds,
while the initial projection spent over eight minutes in relationship and unit
checks before we cancelled it. This attempt is retained as diagnostic evidence.

B added full, file-scoped temporary NSW inputs in C03. They keep original Raw
IDs and values, including excluded years and invalid keys. Non-unique native-key
indexes and temporary-table statistics let PostgreSQL choose bounded joins.
The original key, relationship and projection rules are unchanged. The loader
owns these temporary tables; no permanent table, migration or grant was changed.
New database cases check cold plans, NULLs, duplicates, repeated calls and rollback.

Run those regression fixtures separately from the full snapshot:

```sh
../official-venv/bin/python tools/verify_nsw_cold_plan_postgres.py \
  --output /absolute/path/to/new-nsw-validation-directory
```

An earlier combined run exposed a database statistics issue. After thousands of
rolled-back fixture rows, autovacuum updated relation statistics while the large Raw import was still
uncommitted. The resulting stale statistics made a foreign-key lookup scan all rows
for a source through `raw_file_idx`, then filter by UUID. A separate PostgreSQL
reproduction and the actual nested plan are retained. No planner setting or foreign
key was changed to pass the build.

The full verifier therefore starts in its own database. For a reused database left
by large failed imports or fixtures, A/the database owner should check statistics
and run `ANALYZE raw.record` before retrying if they are stale. This is database
maintenance; `arsia_loader` does not receive owner or maintenance permissions.

## C09 parent lookup

The full run also exposed a slow Unit-to-Crash check. Its plan looked up all
Crash keys for a batch/source/scope, then compared the parent key. B made this
a bounded lateral lookup using all four existing key predicates. Missing and
wrong parents still fail; no business rule, schema or grant changed.

```sh
../official-venv/bin/python tools/verify_c09_cold_plan_postgres.py \
  --output /absolute/path/to/new-c09-validation-directory
```

The new database cases use 1,001 Crashes and 2,001 Units, inspect the actual plan,
reject a valid but incorrect native parent, and verify caller rollback. C owns
the original Canonical implementation; this performance repair is B's addition.

## C06 full-file lookup

The next full run reached C06 but estimated its selected input as two rows.
It repeatedly scanned materialized parent groups for over a million native
rows. B stages the complete selected files in a loader-owned temporary table
and collects its statistics before the same checks. Person rules, registered
cases, count checks and output fields are unchanged.

```sh
../official-venv/bin/python tools/verify_c06_cold_plan_postgres.py \
  --output /absolute/path/to/new-c06-validation-directory
```

The focused checks compare old and new outputs, exercise scaled parent groups
without permanent Raw statistics, and retain the existing C10 and seven-QA
regressions. C owns the original Person implementation; B adds this query-plan
repair and validation. No permanent table, grant or planner setting changes.

## Run

Use Python 3.12 and Docker. Build the wheel and install it outside the checkout:

```sh
python3.12 -m venv ../official-venv
../official-venv/bin/python -m pip install -r requirements-db.txt
../official-venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w ../official-wheel
../official-venv/bin/python -m pip install --no-deps ../official-wheel/arsia_native_intake-0.1.0-py3-none-any.whl
../official-venv/bin/python tools/verify_official_build_postgres.py \
  --native-root /absolute/path/to/raw_datasource \
  --archive-root /absolute/path/to/intake \
  --output /absolute/path/to/new-validation-directory
```

Use a fresh output directory. Add `--prepared-run /absolute/path/to/intake/official/runs/RUN_ID`
to reuse a complete native preparation. Its archived bytes and records are still
checked. The verifier also checks the original seven files against their hashes.
No download replaces a pinned file.

The verifier creates a private PostgreSQL 16.15 database, applies A's unchanged
migrations and checks the original A03 permissions before and after testing.
The database uses the disposable container's writable layer, so the full data
does not compete with PostgreSQL for tmpfs memory. The container and its image
volume are removed at the end. No shared database or release is changed.

For application use:

```python
from arsia_ingest.official import prepare_official_inputs
from arsia_ingest.build import official_request
from arsia_ingest.runner import run_build

prepared = prepare_official_inputs(native_root, archive_root, project_root)
request = official_request(
    connect=connect_loader, project_root=project_root,
    prepared_run=prepared["run_dir"], evidence_root=evidence_root,
)
result = run_build(**request)
```

`connect_loader` must return a fresh `arsia_loader` connection. Keep credentials
outside the repository. The runner owns commits, rollbacks and the shared lock.
Before changing inputs or rules, review their versions and evidence; refreshing
inventory hashes does not approve new data or a wider source scope.

## Reader boundary and deferred dashboard

`arsia_ingest.official_reader.query_official()` takes a reader connection,
`batch_id`, one `source_id`, and `report` (`trend`, `severity`, `units`, `map`).
It delegates permitted reports to D's installed SQL and validates the successful
official batch even when returning an unavailable report. It never reads the
current pointer again or manages the caller's transaction. Responses include
a source label, quality limits and the coverage basis returned by D05.

- Trend and severity results remain source-specific. Interstate totals are unsupported.
- NSW units retain their traffic-unit scope.
- VIC and QLD unit reports return `status="unavailable"`, a reason and `rows=None`.
- All official map reports are unavailable. No invented zero or coverage claim is returned.

D09 can later consume this interface. Its page must show the pinned source,
snapshot, years, definition and restrictions, including VIC's restricted use.
This change does not implement or accept the dashboard.

## Evidence and next owners

See [the validation receipt](evidence/official-build-validation-2026-09-27.json)
for actual test results, input hashes, environment, timings and limitations.
The full tests use real publication, verify caller rollback after publication,
retry the same official snapshot, preserve the successful S0 batch and confirm
`no_change`. Source totals are compared separately with native observations.

E still runs an independent acceptance comparison. D owns the deferred D09
review. A/E and the team confirm the four course decisions in
[E01](e/e01-course-decisions.md). B then updates the expanded inventory and
repeats the affected acceptance cases. The C03, C06 and C09 performance changes are recorded
in B for C to review and adopt separately. `final_platform` remains false.
