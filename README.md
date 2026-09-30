# ARSIA: integrated team runtime

Role B prepares native inputs, loads Raw, freezes manifests, checks input/Raw quality and coordinates the build. A's fixed schema/A06, C's projections and QA, D02–D11 and E's FP1/publication are integrated. S0, S8 and the pinned NSW/VIC/QLD full builds are verified in isolated PostgreSQL. The [official guide](docs/official-build.md) records commands, results and remaining boundaries.

For the Git-and-Docker setup, use the [team Docker guide](docs/team-docker.md).
It separates the persistent development database from disposable acceptance runs.

## Current scope

This version brings the tested `peixian/dev` runtime into the shared baseline. It includes real S0/S8 publication, pinned official builds, the D09 page and the team Docker package. The [main integration record](docs/main-integration.md) lists exact versions and separate follow-up deliveries. Teacher confirmation and the final course materials are still pending.

| Included | Owner |
|---|---|
| Fixed migrations 001–011, loader permissions and A06 Vault loading | A / JJ |
| Native readers, Raw loading, manifest, QA01/QA02 and build runner | B / Peixian |
| Packaged NSW/VIC/QLD projections, VIC location handling, Canonical loading and C10 QA | C / Serenity |
| D02 dimensions, D03 crash facts and D04 reconciliation QA | D / Yihua |
| D05 trend, D06 severity, D07 map and D08 unit queries, with packaged SQL | D / Yihua; B / Peixian for integration and installed-reader validation |
| D09 fixed-release page, D10 QLD evidence and D11 synthetic reports | D / Yihua; B / Peixian for reviewed fixes and integration |
| SQL FP1, publication gate and acceptance checks reused by Docker | E / Aditya; B / Peixian for reviewed fixes and integration |
| Team Docker package and revision checks | B / Peixian; A/E source material retains its authors |

[D05–D08 query integration](docs/analysis-integration.md) is included through [PR #31](https://github.com/A3939/advance-database-assignment-uts/pull/31). Its initial 131 checks used seeded successful batches. The later [official build](docs/official-build.md) verifies real E publication and restricted readers, including B's D08 performance repair. [D09](docs/d09-local-dashboard.md) now reads real published batches, with [official-source restrictions](docs/d09-official-policy.md) shown on the page.

[C10 is connected to B](docs/c10-integration.md), including the [PR #28](https://github.com/A3939/advance-database-assignment-uts/pull/28) QA07 fix. The [real S0 build](docs/full-build-integration.md) and [S8 extension](docs/s8-integration.md) use all seven QA groups and E's actual FP1/publication. Earlier component receipts remain as historical evidence. Current official-scope results are recorded in the [official guide](docs/official-build.md).

The [C/D integration record](docs/cd-integration.md) reports 733 passed / 309 skipped in the installed default suite and 619 passed / 0 skipped in the PostgreSQL-enabled suite. The focused D04 lineage acceptance passed all 31 checks. These suites overlap. The [earlier B10 record](docs/b10-local-validation.md) retains the runner-fix evidence.

The Docker implementation `f9d22c698e2a47559923179da3c76fd7d53b13a6` passed 501 acceptance checks on native ARM64 and emulated AMD64. [Yihua independently replayed that version on Windows x64 / WSL2](https://github.com/A3939/advance-database-assignment-uts/pull/52#issuecomment-5873642661), also passing 501 checks. The later revision-check fix `d4530455944e5ac393440b456b77758c6658962a` passed 63 focused tests and 11 Docker build checks. It has no new full-pipeline or Windows PowerShell result. These records apply to their stated versions. This main integration changes documentation only beyond B's runtime; it does not repeat those runs.

Official results remain source-specific. VIC use stays within the recorded restricted scope; official maps and VIC/QLD unit-detail reports remain unavailable. Neither local publication nor Docker validation grants publisher approval or final course acceptance.

## Branch workflow

- Use `main` as the tested shared baseline and continue unfinished work on each member's branch.
- Bring verified changes into `main` through a PR with scope and test results.
- Keep member, task and fix branches after merging so the work remains easy to trace.
- Use merge commits to retain the original commit history. Integration does not change who owns each module.

## Quick start

For Git-and-Docker startup, initialization, S0, acceptance and the page, follow the [team Docker guide](docs/team-docker.md). Set the revision to the selected full commit and prepare its Git proof before building. No host Python or PostgreSQL is needed for that route.

For native Python development, use Python 3.12 and run these commands from the repository root:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip install --no-build-isolation --no-deps -e .
python -m pytest -q
python tools/create_demo_inputs.py --output artifacts/demo
python -m arsia_ingest --config artifacts/demo/config.json --output artifacts/intake
```

The tests and 19-row demo use synthetic data with all seven native headers, so they need no Git LFS download. The demo generator requires a new or empty directory. To repeat preparation, reuse `artifacts/demo/config.json` or generate a demo elsewhere.

The team's business S0 has separate files and input variants:

```sh
python -m arsia_ingest --config tests/fixtures/s0/config.json --output artifacts/s0-intake
```

To download and prepare the seven official originals:

```sh
git lfs install
git lfs pull
python -m arsia_ingest --config config/native-inputs.json --output artifacts/intake
```

After installation, `arsia-prepare` is an alias for `python -m arsia_ingest`. Keep `raw_datasource/` unchanged. The runner checks each file against the catalogue hash and rejects changed files or unresolved LFS pointers.

Each run gets a new directory under the chosen output root, followed by `<dataset_kind>/runs/`. The JSON receipt gives its `run_dir`, status and counts. Use the output only when `run.json` says `prepared`; `preparing` is incomplete. A full run needs space for archive copies and every retained JSONL record.

## Reading guide

| Document | Contents |
|---|---|
| [Main integration record](docs/main-integration.md) | Source versions, validation scope and remaining role deliveries. |
| [Team Docker setup](docs/team-docker.md) | Installed wheel, private daily/acceptance databases, page, logs and cleanup. |
| [D09 local page](docs/d09-local-dashboard.md) | Fixed-batch reads and real publication checks. |
| [D10 QLD source model](docs/d10-qld-source-model.md) | Native-grain model and executed query evidence. |
| [D11 synthetic reports](docs/d11-synthetic-report-package.md) | Trend, severity and map reports from one published S0 batch. |
| [Native intake guide](docs/native-intake.md) | B01-B05: configuration, parsing rules, L1 fields, failures and database integration. |
| [VIC source review](docs/sources/vic-accident-vehicle.md) | B06: source definitions, four-file findings and questions for C. |
| [S0 input guide](docs/s0-inputs.md) | B07: sample values, generation commands and input variants. |
| [S8 input guide](docs/s8-inputs.md) | AT15: fourth-state synthetic inputs, bad-key variant and manifest definitions. |
| [Raw loading guide](docs/raw-loading.md) | B08: registration, ID reuse, payload conflicts, connection ownership and tests. |
| [Manifest guide](docs/manifest.md) | B09: complete build inputs, frozen definitions and E's installed FP1 call. |
| [VIC restricted input support](docs/vic-restricted-inputs.md) | B09/B11: adopted policy, exact case/evidence bindings and restricted QA01. |
| [Input QA guide](docs/input-qa.md) | B11: per-file native and Raw comparisons, source reviews and evidence. |
| [Three-source C/D integration](docs/cd-integration.md) | Actual bindings, partial inventory, installed-package and PostgreSQL validation. |
| [S0 QA01–QA07 joint validation](docs/qa-joint-validation.md) | Seven QA groups, stored results, fault cases and component-validation limits. |
| [D05–D08 query integration](docs/analysis-integration.md) | Query packages, SQL deployment, inventory and installed-reader checks. |
| [Peixian's contribution record](docs/contributions/peixian.md) | B implementation, cross-role fixes and integration evidence. |
| [Build runner](docs/runner.md) | B10: module bindings, shared connection, transactions and run results. |
| [Full S0 build](docs/full-build-integration.md) | Installed A/B/C/D/E bindings, inventory, publication and recovery. |
| [Full S8 build](docs/s8-integration.md) | AT15: synthetic fourth source, publication, history and coverage checks. |
| [Pinned official build](docs/official-build.md) | NSW/VIC/QLD admission, full-volume verifier, restricted reader interface and handoff. |
| [B10 local validation](docs/b10-local-validation.md) | Transaction and failure-evidence fixes, installed-package tests and remaining build dependencies. |
| [Runner lock checks](docs/runner-locks.md) | B12: real session locks, busy exit and early-failure cleanup; remaining build checks. |
| [Run recovery](docs/recovery.md) | B14: resolve uncertain commits and abandoned runs; scope and validation are recorded in the guide. |
| [B06/B07 validation](docs/b06-b07-validation.md) | Tests and S0 preparation recorded on 2026-09-17. |

The earlier [2026-09-15 validation](docs/native-intake.md#recorded-validation-2026-09-15) records the full-input run and its counts.

## Repository layout

| Path | Purpose |
|---|---|
| `src/arsia_ingest/` | Readers, archives, configuration checks and preparation runner. |
| `src/arsia_ingest/raw_load.py` | B08 loader using the caller's connection; no migration or automatic commit. |
| `src/arsia_ingest/manifest.py`, `fingerprint.py` | Manifest validation/freezing and E's explicit SQL call boundary. |
| `src/arsia_ingest/qa_input.py`, `runner.py` | QA01/QA02, evidence and the shared build lifecycle. |
| `src/arsia_ingest/recovery.py` | Resolve a saved run using a new connection, without retrying the build. |
| `src/arsia_ingest/build.py`, `official.py`, `official_definitions.py` | S0/S8 and pinned official build requests, preparation and source admission. |
| `src/arsia_ingest/official_reader.py` | Source-specific official reports with explicit unavailable outputs. |
| `src/arsia_d05/` through `src/arsia_d08/` | Fixed-batch query APIs and packaged SQL; these are read APIs, not B10 load callbacks. |
| `src/arsia_d09/` | Local fixed-release page, SQL, templates and static resources; installed as `arsia-dashboard`. |
| `docker/team/`, `compose*.yaml` | Pinned images, build proof, installed-wheel commands and separate acceptance environment. |
| `config/analysis-inventory.json` | Query paths, hashes, versions and deployment dependencies; a partial inventory. |
| `config/qa-team-v1.1.json` | Unchanged English QA text from team contract 04 §3. |
| `config/native-inputs.json` | Seven resources, 197 ordered field names, workbook settings and file hashes. |
| `raw_datasource/` | Original source files managed by Git LFS. |
| `tests/` | Synthetic regression tests and opt-in PostgreSQL/full official snapshot checks. |
| `tools/create_demo_inputs.py` | Generates the 19-row reader demo. |
| `config/synthetic-s0.json`, `tools/create_s0_inputs.py` | S0 definitions and variant generator. |
| `tests/fixtures/s0/` | Seven shared S0 files, intake configuration and fixture contract. |
| `config/synthetic-s8.json`, `tests/fixtures/s8/`, `tests/fixtures/s8-bad-key/` | S8 definition and two eight-resource configurations sharing the original S0 files. |
| `tools/profile_vic_inputs.py` | Read-only VIC checks with hashes, counts and anomaly locations. |
| `artifacts/` | Local run output, excluded from Git. |

## Output and scope

A prepared run contains one JSONL file per resource, file metadata in `files.json`, separate provenance, a run summary and logs. Each L1 row has six keys:

```text
source_id, resource_id, file_sha256, parser_version, row_locator, payload
```

CSV values remain text, including blanks and leading zeros; XLSX conversion follows the intake guide. Person rows, Node observations and QLD aggregate fields are retained. Filtering, business mappings and deduplication belong to later steps.

`prepared` means native input preparation passed. The [C/D integration](docs/cd-integration.md) verifies three-source S0 loading through crash facts. C10 has an installed `qa_c` binding, and [all seven QA groups](docs/qa-joint-validation.md) have passed joint S0 component checks with persisted results. [D05–D08 reader checks](docs/analysis-integration.md) cover installed queries, permissions and fixed batches using seeded successful test states.

[B12's lock checks](docs/runner-locks.md) cover session contention and early cleanup. The [B10 local validation](docs/b10-local-validation.md) covers transaction isolation, failure evidence and recovery markers. The [complete S0 runner checks](docs/full-build-integration.md) add real E publication, repeated builds, snapshot changes, concurrency and recovery. The [S8 extension](docs/s8-integration.md) is also verified. The [official run](docs/official-build.md) passed full-snapshot publication, rollback, retry and reader checks. D09 and the team Docker package are integrated. E's historical acceptance and Yihua's independent Docker replay are recorded at their exact versions in the [main integration record](docs/main-integration.md). Final teacher confirmation and course submission remain open. B09/B11 retain the agreed VIC restrictions.

The baseline is team v1.1: document 04 (L1 contracts and acceptance) and document 05 (sources and mappings, sections 1-2 and 7). The [online database design](https://arsia-team-design.vercel.app/) shows the shared model. Links in the guides to `F/` and `Resources/` refer to the shared course workspace outside this Git repository; they work locally but are unavailable in a standalone clone or on GitHub.
