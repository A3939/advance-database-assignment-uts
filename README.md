# ARSIA: shared development baseline

This A checkout keeps the original shared application baseline and adds the A01/A09 environment handoff. For the current runnable S0 build, use the [cold-start guide](docs/cold-start-and-schema-maintenance.md). It installs a pinned B integration in a separate checkout and venv.

## Current scope

This baseline brings the tested integration from `peixian/dev` at `a469dda` into `main`. It is a shared starting point for development. Full platform acceptance is still pending.

| Included | Owner |
|---|---|
| Fixed migrations 001–011, loader permissions and A06 Vault loading | A / JJ |
| Native readers, Raw loading, manifest, QA01/QA02 and build runner | B / Peixian |
| Packaged C03 NSW projection and C09 Canonical loading | C / Serenity |
| D02 Source, Month and Severity dimensions | D / Yihua |

The table describes this baseline, not current team progress. B commit `562de2910bfd7be276b3036983e5680d436fde1e` includes the later C/D integration, C10 QA, E FP1 and publication callbacks. The cold-start guide tests that fixed version without copying it into A's branch. Final platform acceptance remains separate.

The [B10 validation record](docs/b10-local-validation.md) reports 615 passed / 155 skipped in the installed default suite and 377 passed / 0 skipped in the PostgreSQL-enabled suite. These suites overlap and cover the stated component scope.

## Branch workflow

- Use `main` as the tested shared baseline and continue unfinished work on each member's branch.
- Bring verified changes into `main` through a PR with scope and test results.
- Keep member, task and fix branches after merging so the work remains easy to trace.
- Use merge commits to retain the original commit history. Integration does not change who owns each module.

## Quick start

Use Python 3.12 and run these commands from the repository root:

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
| [Native intake guide](docs/native-intake.md) | B01-B05: configuration, parsing rules, L1 fields, failures and database integration. |
| [VIC source review](docs/sources/vic-accident-vehicle.md) | B06: source definitions, four-file findings and questions for C. |
| [S0 input guide](docs/s0-inputs.md) | B07: sample values, generation commands and input variants. |
| [S8 input guide](docs/s8-inputs.md) | AT15: fourth-state synthetic inputs, bad-key variant and manifest definitions. |
| [Raw loading guide](docs/raw-loading.md) | B08: registration, ID reuse, payload conflicts, connection ownership and tests. |
| [Manifest guide](docs/manifest.md) | B09: complete build inputs, frozen definitions and the proposed FP1 call. |
| [VIC restricted input support](docs/vic-restricted-inputs.md) | B09/B11: adopted policy, exact case/evidence bindings and restricted QA01. |
| [Input QA guide](docs/input-qa.md) | B11: per-file native and Raw comparisons, source reviews and evidence. |
| [Build runner](docs/runner.md) | B10: module bindings, shared connection, transactions and run results. |
| [B10 local validation](docs/b10-local-validation.md) | Transaction and failure-evidence fixes, installed-package tests and remaining build dependencies. |
| [A09 cold-start and schema maintenance](docs/cold-start-and-schema-maintenance.md) | Empty PostgreSQL 16 rebuild, migration order, schema/dictionary verification, failure diagnostics and acceptance boundary. |
| [Runner lock checks](docs/runner-locks.md) | B12: real session locks, busy exit and early-failure cleanup; remaining build checks. |
| [Run recovery](docs/recovery.md) | B14: resolve uncertain commits and abandoned runs; real state recovery awaits integration. |
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
| `config/qa-team-v1.1.json` | Unchanged English QA text from team contract 04 §3. |
| `config/native-inputs.json` | Seven resources, 197 ordered field names, workbook settings and file hashes. |
| `raw_datasource/` | Original source files managed by Git LFS. |
| `tests/` | Tests using small synthetic files. |
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

`prepared` means native input preparation passed. The [A/C integration](docs/ac-integration.md) verifies S0 input-to-Canonical loading and QA01/QA02 persistence. [B12's lock checks](docs/runner-locks.md) cover session contention and early cleanup. The latest [B10 local validation](docs/b10-local-validation.md) covers transaction isolation, failure evidence and recovery markers. Real FP1, complete C/D QA and publication remain unverified. B09/B11 enforce the adopted VIC input restrictions; full downstream integration is still required.

The baseline is team v1.1: document 04 (L1 contracts and acceptance) and document 05 (sources and mappings, sections 1-2 and 7). The [online database design](https://arsia-team-design.vercel.app/) shows the shared model. Links in the guides to `F/` and `Resources/` refer to the shared course workspace outside this Git repository; they work locally but are unavailable in a standalone clone or on GitHub.
