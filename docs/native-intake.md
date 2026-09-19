# Native input preparation

This guide covers Role B's readers, archives and L1 output under team-v1.1. Preparation needs source files and a configuration. The separate [B08 guide](raw-loading.md) covers loading prepared records on a supplied database connection.

## 1. Inputs and configuration

`config/native-inputs.json` lists seven resources with file paths relative to the configuration. These are B's initial intake IDs; official release groups and business definitions still need team review.

| Resource ID | Source ID | Native file | Fields | Format / sheet |
|---|---|---|---:|---|
| `official_nsw_crash` | `official_nsw` | `nsw_crash_2020_2024.xlsx` | 50 | XLSX / `Sheet1` |
| `official_nsw_traffic_unit` | `official_nsw` | `nsw_traffic_unit_2020_2024.xlsx` | 10 | XLSX / `Export` |
| `official_vic_accident` | `official_vic` | `vic_accident.csv` | 23 | CSV |
| `official_vic_vehicle` | `official_vic` | `vic_vehicle.csv` | 37 | CSV |
| `official_vic_person` | `official_vic` | `vic_person.csv` | 14 | CSV |
| `official_vic_node` | `official_vic` | `vic_node.csv` | 11 | CSV |
| `official_qld_crash` | `official_qld` | `qld_crash_locations.csv` | 52 | CSV |

The 197 field names and their order follow document 05, section 7. File hashes check for changed bytes; source evidence establishes meaning and release compatibility.

The configuration has three top-level fields:

```text
config_version: "intake-v1"
dataset_kind: "official" | "synthetic"
resources: [resource specifications]
```

Each resource has `source_id`, `resource_id`, `resource_role`, `entity_kind`, `path`, `format`, `encoding`, `sheet`, `header_row`, `header` and an optional `expected_sha256`. The supplied official catalogue includes a hash for every file. CSV uses `encoding="utf-8"` and `sheet=null`. XLSX uses `encoding=null` and a named sheet. Both formats have their header on row 1. The supported entity kinds are `crash`, `unit`, `person_raw` and `node_raw`.

Use separate configurations for official and synthetic inputs. Intake-v1 requires `official_` and `syn_` source/resource prefixes respectively, and stores output in separate dataset-kind directories. Database batch and current-release isolation remain integration work. Section 3 explains the additional fields needed for the full L1 manifest.

## 2. Native parsing rules

| Topic | Rule |
|---|---|
| CSV encoding | Decode UTF-8; accept and strip only a BOM at the beginning of the file. Invalid encoding blocks preparation. |
| CSV records | Follow CSV quoting rules, including escaped quotes and embedded newlines. A quoted newline stays inside its record. Every retained value is text, including `""`, whitespace, `NA`, `Unknown` and `0001`. |
| CSV blank records | Skip and log only empty logical records parsed as `[]`. Keep quoted empty fields, delimited rows of empty values and whitespace values. A row with the wrong number of fields fails preparation. |
| XLSX text and blanks | Read the configured sheet. Keep text unchanged and write empty cells as JSON `null`. A numeric 1 displayed as `0001` becomes `"1"`, while a text cell containing `0001` stays `"0001"`. Display formatting must not be used to build record identities. |
| XLSX numbers | Write finite numbers as fixed decimal text without exponent notation. The archive keeps the original workbook and formatting. Business rounding, unit conversion and missing-code interpretation are left to later steps. |
| XLSX dates | Write actual dates as `YYYY-MM-DD`, datetimes as `YYYY-MM-DDTHH:MM:SS` and times as `HH:MM:SS`. Add six fractional digits when the fractional second is nonzero. Leave the time zone unspecified. Do not reinterpret ordinary text or numeric cells as business dates. |
| XLSX unsupported values | Formulas, errors, booleans and unsupported cell types fail preparation after the file has been archived. Cached formula results are not used. |
| XLSX blank rows | Keep all-null rows if data appears later in the sheet. Skip and count all-null rows at the end. Keep the original worksheet row numbers. |
| Header validation | Check the full header against the catalogue, including its order. Missing, extra, renamed, duplicated or reordered columns fail preparation. |
| Scope | Keep all retained native records, including repeated observations and rows outside 2020–2024. Business keys, filtering, merging, deduplication and value mappings belong to downstream contracts. |

Parser versions are `csv-native-v1` and `xlsx-native-v1`. Changes to values, retained rows or positions require a review of parser and locator versions because they affect record identity.

### Row locators

CSV uses `csv-logical-v1`. Count logical records from 1 after the header, including skipped empty records. A newline inside a quoted field is part of the same record. Skipping a blank can therefore leave a gap, such as `csv:1`, `csv:3`.

XLSX uses `xlsx-physical-v1`. The locator is a JSON array stored as text, containing the sheet name and original row number, for example `["Sheet1", 2]`. Data starts on row 2. The text uses a comma followed by one space, normal JSON string escaping and literal Unicode (`ensure_ascii=False`). Keep this text exactly as emitted when loading it later; reformatting it would change the record's identity.

Both locators refer to positions in the archived source. Two rows with the same payload still have separate locators.

## 3. Outputs and identities

After setting up the environment using the README, download the Git LFS files and run preparation from the repository root:

```sh
git lfs install
git lfs pull
python -m arsia_ingest --config config/native-inputs.json --output artifacts/intake
```

Each run writes the following files:

```text
artifacts/intake/
  official/                         # synthetic/ for a synthetic configuration
    archive/sha256/<first-two-hash-characters>/<file-sha256>
    runs/<run-uuid>/
      records/<resource_id>.jsonl
      files.json
      provenance.json
      run.json
      events.jsonl
```

The archive stores an unchanged input copy under its SHA256 hash. The runner verifies the copy before the reader parses it; later runs can reuse it if the hash still matches. A mismatch stops preparation. Moving the source file does not change its hash, but each preparation gets a new ID. B10 handles database-level `no_change` after FP1.

### L1 rows

Each JSONL line is a UTF-8 JSON object with six top-level fields:

| Member | Content |
|---|---|
| `source_id` | Source ID from the configuration. |
| `resource_id` | Resource ID from the configuration. |
| `file_sha256` | SHA256 of the original file bytes. |
| `parser_version` | Version of the native reader. |
| `row_locator` | Original logical record or worksheet row position, stored as text. |
| `payload` | Every original header paired with its native text or null value. |

A two-column synthetic CSV could produce the row below. Actual resources include every header field.

```json
{
  "source_id": "syn_example",
  "resource_id": "syn_example_crash",
  "file_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "parser_version": "csv-native-v1",
  "row_locator": "csv:1",
  "payload": {"ACCIDENT_NO": "0001", "SEVERITY": ""}
}
```

The zero-filled hash is an example placeholder. Actual runs calculate it from the file. B08 uses `(resource_id, file_sha256, parser_version, row_locator)` to return or reuse `raw_record_id`, rejecting a different payload for an existing identity. The reader does not assign database UUIDs; the separate loader generates them for new rows.

### File metadata and provenance

`files.json` contains one top-level `files` array. Each entry has 13 fields:

```text
source_id, resource_id, resource_role, entity_kind,
file_sha256, parser_version, locator_version, format,
encoding, sheet, header_row, header, raw_count
```

`header` preserves column order. `raw_count` includes all retained records, including those that may fail later business checks. Blank counts and local paths are stored separately.

`provenance.json` contains `run_id`, `dataset_kind` and `files`. File entries hold `resource_id`, `file_sha256`, `archive_relpath`, `original_filename` and `input_path`. Archive paths are relative to the output root and include the dataset kind, for example `official/archive/sha256/ab/<hash>`. When moving an output directory, use its relative archive and record paths. Absolute `input_path`, `config_path` and `run_dir` values describe the original run location.

`run.json` records the run ID, tool/output versions, dataset kind, `native_preparation_only` scope, UTC timestamps, status and errors. Each prepared resource includes its input byte size, relative `records_path`, `records_sha256`, observed header and parsing counts. The top-level `raw_count` totals all resources. `events.jsonl` records progress, archive references, parse counts and errors. `records_sha256` identifies the JSONL output, separately from the source-file hash and FP1.

`files.json` supplies only the manifest's `files` section. [B09](manifest.md) adds the remaining definitions, checks the build inventory and freezes the snapshot. FP1 still needs E's SQL; Python file hashes and JSON serialization do not produce the database fingerprint.

## 4. Failure and rerun behaviour

Check `run.json` before using output. `prepared` means all configured files finished; `preparing` is incomplete, including after a killed process. One failed resource fails the whole run, so none of that run's exports may be loaded.

On a caught processing error, the runner removes partial records, `files.json` and `provenance.json`, retaining archives and diagnostics in `run.json` and `events.jsonl`. Cleanup or receipt writing can also fail. File existence alone is therefore insufficient; use the final status.

Diagnostics identify the resource, file and, where relevant, record or cell. Errors include missing files, unresolved LFS pointers, hash or header mismatches, invalid encoding, NUL characters unsupported by PostgreSQL text/JSONB, malformed rows and unsupported Excel cells. Fix the source or configuration issue and start a new run rather than editing generated JSONL.

The CLI returns `0` for prepared input, `1` for processing failures and `2` for configuration or command-line usage errors. Rejected configurations have no run directory. Setup errors can also occur before a receipt is written.

`prepared` is an intake status. Keep it separate from the database batch status `succeeded`; database loading, official QA and publication still need their own results.

## 5. Tests and later integration

Run the tests from the repository root:

```sh
python -m pytest -q
```

To try the readers with all seven native headers:

```sh
python tools/create_demo_inputs.py --output artifacts/demo
python -m arsia_ingest --config artifacts/demo/config.json --output artifacts/intake
```

The tests and 19-row reader demo use synthetic files, without a Git LFS download. Generate into a new or empty directory, or reuse an existing `config.json` for another intake run. Business S0 uses separate inputs; its expected 63-row QA result set still needs pipeline verification.

See the [S0 input guide](s0-inputs.md) for `tests/fixtures/s0/` and its variant generator, the [VIC source review](sources/vic-accident-vehicle.md) for C's open questions, and the [2026-09-17 validation](b06-b07-validation.md) for their test results.

Tests cover native values, row positions, structural errors, archives and failure cleanup. The official catalogue uses the same readers. Business mappings, severity definitions, state coverage, release compatibility and CRS require separate verification. B08's connection tests and opt-in PostgreSQL tests are described in the [Raw loading guide](raw-loading.md); mocked calls are not proof of actual database loading.

### Recorded validation (2026-09-15)

On 2026-09-15, all 123 tests passed with Python 3.12.6, openpyxl 3.1.5 and pytest 8.4.2. Two runs of the seven-resource, 19-row demo produced identical `files.json` and JSONL bytes.

The full-source run using the command in §3 returned `prepared` for 7 resources, 197 native fields and 2,118,028 retained records. All reported CSV blank-record and XLSX trailing-row skip counts were zero.

| Resource | Retained records |
|---|---:|
| NSW Crash | 92,189 |
| NSW Traffic Unit | 170,962 |
| VIC Accident | 200,352 |
| VIC Vehicle | 365,470 |
| VIC Person | 467,730 |
| VIC Node | 405,918 |
| QLD Crash | 415,407 |
| **Total** | **2,118,028** |

The run ID was `ac93f011-1d92-4847-8386-01614b76302b`. Its local evidence is stored in `artifacts/full-intake-result.json` and `artifacts/intake/official/runs/ac93f011-1d92-4847-8386-01614b76302b/`, which are excluded from Git. The receipt recorded 36.901 seconds on this machine. Timing will vary between runs.

The audit recorded in `artifacts/full-output-audit.json` passed the contract, identity, locator-sequence and count/hash checks for every output row. All values and locators from the five CSVs matched their originals, and the seven source-file hashes were unchanged. A replay with the final XLSX reader reproduced every exported payload and locator. Reader tests covered the cell-conversion edge cases. These are the recorded preparation results from that date.

### Sharing a prepared run

When sharing a run with A/C/E, include:

1. The code revision, dependency versions, exact command, configuration and run location.
2. The `prepared` output for every configured resource, with its L1 rows and file metadata.
3. Provenance linking each resource hash to its checked archive copy.
4. Row counts, skipped-blank counts and results from normal and error-case tests.
5. Any open questions about the sources or contracts.

The next integration steps depend on these shared parts:

| Next work | Coordination needed |
|---|---|
| Insert/reuse `meta` and `raw` records and receive `raw_record_id` | A's schema, constraints, permissions and SQL interface. |
| Use the B09 manifest and connect FP1 | Team code/schema files, versioned source rules and E's registered SQL operation. See [manifest.md](manifest.md). |
| Convert native fields into typed business projections | C's rules, identities and diagnostics; B passes original values unchanged. |
| Execute the full pipeline and manage commit/rollback | [B's runner](runner.md), using the same connection for A/C/D/E's modules. |
| Produce QA and select the current successful release | B/C/D's checks; E's object-completeness check and publication gate. |

[QA01/QA02](input-qa.md) now replay native archives and compare the selected Raw records. Their PostgreSQL checks still need A's environment. Official source contracts remain drafts pending evidence and team confirmation.
