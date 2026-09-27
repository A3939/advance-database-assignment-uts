# B10: real S0 build

B now connects E's FP1 and publication gate to the installed A/C/D modules.
`arsia_ingest.build.s0_request()` supplies a real `FrozenManifest`, all seven
callbacks and the reviewed inventory. The runner commits a successful release;
the tests do not seed its status or pointer.

This page records the original three-source S0 integration. B's later
[S8 extension](s8-integration.md) uses the same runner and adds the declared
synthetic SA source; its commands and results are recorded separately.

## Versions and ownership

- B base: `6ec0f892519e83ee028cc987ed7c9479d1b24648`.
- A schema/A06: `c0824da06b6e7b3f73c4ddeab2114d10b7156913`, migrations 001–011.
- C: integrated C03–C10 code, including QA07 fix `6987e604bb93809aa94a736085c3e8320452461d`.
- D: `d57c3f4ff2fb57eb84ebc414ef77911073c0de06`, D02–D08.
- E: PR #16 head `aec3b4692382e48ea4f778f04a31a4ca5ba5fa57`, including PR #30. PR #16 merged into B as `8046795` after Peixian's re-review.

Aditya wrote the original E delivery, including FP1 (`ac06a93`) and the gate
(`2334444`). Peixian repaired these in `0929eed` and `8092765`, then added this
B integration, packaging and validation. The merge keeps their original commits.
A/C/D retain authorship of their modules. This is B's integration review, not an
independent approval by E.

## Entry and inventory

`src/arsia_ingest/build.py` contains `build_modules()`, `FP1`, `fp1_sql()` and
`synthetic_request()`, `s0_request()` and `s8_request()`. The two named recipes
select the checked-in S0 or S8 contract; `synthetic_request()` takes an explicit
contract path. They reuse `components.bindings()` and add E's real `publish`.
The SQL resource `src/arsia_ingest/sql/fp1.sql` is byte-identical to E's
`sql/e/fp1.sql`; both are hashed and the installed resource is checked.

`config/build-inventory.json` includes all 11 component groups, every runtime
Python/SQL/JSON file, requirements, package metadata and A's 11 migrations.
`complete_build: true` describes the installed synthetic build, including S0 and
S8. `final_platform: false` keeps D09 and official/platform acceptance outside
that claim. Existing
component inventories remain partial. Their package hashes were refreshed.

The runtime checks the declared hashes before freezing. After reviewing a code
change, run `python tools/update_build_inventory.py`, inspect its diff, rebuild
the wheel and repeat validation. Do not refresh hashes just to bypass a failure.

Apply A's migrations as documented, then deploy `fp1_sql()` as the owner. The
adapter pins PostgreSQL 16.15, UTF-8 and UTC. It checks the SQL file and database
function signature; deployment and execution tests establish what actually runs.
Use a fresh `arsia_loader` connection for each build:

```python
from arsia_ingest.build import s0_request
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import run_build

prepared = prepare("tests/fixtures/s0/config.json", "artifacts/native")
request = s0_request(
    connect=connect_loader, project_root=repo_root,
    prepared_run=prepared["run_dir"], evidence_root="artifacts/builds",
)
result = run_build(**request)
print(result.as_dict())
```

`connect_loader` is A's connection factory; keep credentials outside the repo.
Use the same native archive root for successive snapshots. QA01 reads previous
file versions from that store. For a generated S0 variant, pass its
`contract.json` as `contract_path`. For S0 plus SA, prepare the S8 inputs and use
`s8_request()` as shown in the [S8 guide](s8-integration.md). Source support is
checked by the installed projections; the runner has no fixed source count.

## Reproduce

Use Python 3.12 and Docker. Choose new output paths. The venv and test working
directory must be outside the checkout; this prevents source-tree imports.

```sh
python3.12 -m venv ../b10-venv
../b10-venv/bin/python -m pip install -r requirements-db.txt
../b10-venv/bin/python -m pip wheel --no-deps --no-build-isolation . -w ../b10-wheel
../b10-venv/bin/python -m pip install --no-deps ../b10-wheel/arsia_native_intake-0.1.0-py3-none-any.whl
../b10-venv/bin/python tools/verify_full_build_postgres.py --output ../b10-postgres
```

The verifier removes `PYTHONPATH`, compares installed files with the inventory,
checks A's migration bytes, creates a private PostgreSQL 16.15 container and
runs the original A03 audit before and after. It saves commands, environment,
input hashes, pytest results and cleanup evidence, then removes the container.
It creates no persistent volume and never uses a shared database.

## Checks and limits

The original S0 integration suite passed **334 tests**, including **112 PostgreSQL cases**
(61 new runner cases and 51 E regressions), with no skips or failures. The
installed default suite passed **812 tests**, with 377 optional checks skipped.
These totals overlap. The [receipt](evidence/full-build-validation-2026-09-27.json)
records report hashes. The selected tests cover:

- Baseline: 19 Raw rows; 6 crashes, 6 units and 6 facts; 3 sources, 60 months,
  12 severity definitions, including unused values and `__MISSING__`.
- Seven QA groups: 56 concrete rows plus 7 summaries. QA07 correctly remains
  `limited` for two crashes. E checks the real producer evidence before commit.
- Repeated input returns `no_change`; changed rules, corrected deaths and an
  explained deletion publish new batches without rewriting old results.
- Unexplained deletion and invalid keys, dates, counts, categories or Person
  references cannot publish. Permitted location limits keep the crash rows.
- Failures after real Vault, DW and publication calls roll back candidate
  writes, preserve the previous release and save a failed batch and evidence.
- Concurrent builds return `busy`; a lost publication acknowledgement resolves
  from the committed database state through B14 without rebuilding.
- D05–D08 run as `arsia_reader` against E-published batches. A pinned old batch
  stays stable after the pointer changes.
- All 51 existing E PostgreSQL regressions run against the new build manifest;
  43 gate-fault cases also run through the complete runner.

Normal builds use actual loader logins. Fault-injection tests use the owner only
to damage test QA rows, then restore `arsia_loader` before the real E gate.
A03 grants are unchanged. Failure wrappers call the real module before raising;
they are test probes, not alternate production bindings.

Remaining work: D supplies/reviews D09; the team verifies admitted official
inputs; E runs an independent acceptance comparison; A/E confirm the
four open course decisions in `docs/e/e01-course-decisions.md`. B then freezes
that expanded platform inventory and reruns the relevant acceptance cases.
No official release, dashboard acceptance or team-wide completion is claimed.
