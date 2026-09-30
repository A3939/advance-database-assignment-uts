# B11: input and Raw checks

[`qa_input.py`](../src/arsia_ingest/qa_input.py) implements `QA01_INPUT` and `QA02_RAW`, with one result per frozen file and a batch summary. Native checks have passed, along with synthetic Raw comparisons on real PostgreSQL. B11 also supports the adopted VIC restricted-use protocol. [Joint S0 validation](qa-joint-validation.md) now verifies QA01/QA02 persistence alongside C and D results. Official publication remains separate.

## Shared API

```python
from arsia_ingest.qa_input import check_inputs, check_raw, write_evidence, write_results

input_report = check_inputs(
    frozen.as_dict(), archive_root,
    previous_manifest=previous_manifest,
    evidence_dir=run_evidence / "input", producer_version="b11-v1",
    supported_mappings=accepted_mappings,
    official_reviews=source_reviews,
)
raw_report = check_raw(
    connection, frozen.as_dict(), archive_root,
    evidence_dir=run_evidence / "raw", producer_version="b11-v1",
)
```

`archive_root` is the intake output root containing `synthetic/archive/sha256/` and `official/archive/sha256/`. Current and previous archives must be available there. `previous_manifest=None` means the runner has checked that this mode has no previous publication; it is not a switch for skipping history.

A `QAReport` exposes `rows`, `blocked` and `as_dict()`. Save it with `write_evidence(path, report.as_dict())` before handling a block. Once a batch exists, `write_results(connection, batch_id, report)` inserts into `qa.check_result` without updating earlier results. After a database error, the runner must preserve file evidence and roll back before further writes.

Database functions use the caller's `autocommit=False` connection and leave its lifecycle to the runner. Checks without a batch stay in file evidence.

## QA01_INPUT

The checker replays archived CSV/XLSX with the existing reader. It checks hashes before and after replay, ordered headers, format, parser/locator versions and row counts. Unsupported parsers, unreadable files and incomplete checks block.

`accepted_mappings` contains the mapping owner's `{id, version, content}` entries. Each mapping must match in full; unknown operations and changed rules block. Synthetic checks can use the shared S0 definitions. This checks declared mappings, not C's installed SQL.

Under the legacy protocol, official contracts need confirmed review records as well as their frozen confirmation section. `source_reviews` is a list with these fields:

```text
resource_id, contract_version, file_sha256, release_label, release_scope,
status="confirmed", bundle_confirmed=true, reviewed_by,
references=[...], unresolved=[]
```

Identity/version fields must match the manifest, and references must identify the source review and evidence. B consumes these reviews; it does not approve sources. Draft contracts, missing reviews and nonempty `unresolved` block. The historical [VIC review](sources/vic-accident-vehicle.md) does not establish unrestricted approval. The adopted `team-v1.1-vic-r1` path uses its own exact policy and expectations; it does not change legacy results.


For the [restricted VIC profile](vic-restricted-inputs.md), the four file objects have eight metrics. `bundle_confirmed` and `contract_confirmed` must remain false; `profile_approved`, `selected_identity_match`, `profile_scope_match`, `case_register_match`, `hash_match` and `header_match` must be true. `case_register_match` checks the frozen register and cited evidence bytes, not downstream semantic SQL. Missing or changed evidence blocks; checks not reached retain null metrics.

Evidence is read from the repository by default. `policy_evidence_root` may point to a relocated repository with the same pinned files. Do not supply `official_reviews` for these VIC files: unrestricted review records conflict with the selected profile. Other sources still need their normal reviews. QA02 is unchanged and compares every native field and locator regardless of registered semantic exceptions.

Later snapshots are compared by native key counts, so a deletion is detected even when total rows stay unchanged or increase. Duplicate Node keys remain observations. Missing historical archives or changed key definitions block.

The existing S0 change statement identifies `source_id`, `previous_release_label`, `kind`, `native_key` and `description`. Deletions require `kind="deletion"` or `"replacement"`; several keys may use `native_keys`. An optional `resource_id` restricts the statement to one resource. Removing an entire resource blocks pending a contract review.

Coverage reductions require `kind="coverage_reduction"` or `"replacement"`, a nonblank description and `coverage={"before": ..., "after": ...}`. This implements the change statement in 04 §3 and 05 §5. Both values must match the complete previous/current `identity.coverage`, including types and any `basis`. A boolean, old range or incomplete pair blocks; evidence keeps the declared and actual ranges.

This comparison supports integer `year_from`/`year_to` (1–9999, in order), a nonempty list of distinct integer `months` (1–12), and optional nonblank `basis`. Booleans are not integers here. A year/month expansion needs no reduction statement only when the basis stays unchanged. Other changed coverage shapes, such as regional subsets, remain blocked until a suitable comparison is agreed.

## QA02_RAW

The checker reads native archives directly. A temporary SQLite index holds native locators and payloads and is deleted afterwards. Raw rows are read in pages of at most 1,000 UUIDs on the supplied connection.

Every row is compared by resource, file hash, parser, source, original locator and complete payload. Missing/extra rows, duplicate locators, omitted/extra fields, changed strings, numbers replacing strings, and `NULL` versus empty-string differences block. Node observations with different locators stay separate. Other snapshots in Raw are outside the selected file identity.

QA01 `evaluated_count` counts files (one per concrete result). QA02 counts distinct native locators actually matched against Raw; its expected count is the frozen native row count. An unavailable Raw check has null metrics and a block result. Batch summaries count concrete results and sum their affected counts once. Only QA07 may report `limited`.

## Evidence and checks

Each file result references a create-only JSONL detail file with its SHA256 and row count. Differences retain resource, hash, locator and the Raw UUID when available. `write_evidence(path, value)` returns `{path, sha256, row_count}` and refuses an existing path. The runner supplies the evidence directory.

## Validation

The [2026-09-20 receipt](evidence/b11-postgres-validation-2026-09-20.json) records two full-suite runs:

| Environment | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Original `.venv`, no `ARSIA_TEST_DSN` | 416 | 10 | 0 |
| Existing PostgreSQL test environment, `arsia_loader` | 426 | 0 | 0 |

The second run used Python 3.12.6, Psycopg 3.3.6 and PostgreSQL 16.15 from the [B08 reproduction](b08-postgres-review.md). No dependencies or migrations were added. The ten real database tests are eight B08 tests and two QA02 tests; the other database-facing tests still use mocks.

The successful QA02 case first ran QA01 over all seven S0 archives, then loaded and compared all 19 Raw rows, preserving the four Node observations. QA01 and QA02 each produced seven file passes and one batch pass. The second case changed one `Crash ID` in Raw while keeping the row count unchanged. QA02 blocked that file and the batch, retaining the UUID, locator and expected/actual payload. Both tests now save their manifests and full reports as well as detail files.

The receipt includes per-file measurements and the mismatch evidence. Full reports and pytest output remain in `artifacts/b11-postgres-validation-2026-09-20/`. Every write was rolled back; the three tables were empty before and after testing. The container was stopped afterwards, with its volume retained. Test manifests use an explicit test-only code inventory, so these runs do not verify FP1 or a deployed build.

To repeat the local suite without a database:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

For the two real database cases and the native QA regression tests, start the isolated test database, set `ARSIA_TEST_DSN` to its loader connection and use `PGPASSFILE` for the password. The mapped port can change after restart; it must match both settings. The existing local driver environment is:

```sh
PYTHONDONTWRITEBYTECODE=1 \
artifacts/b08-db-reproduction-2026-09-20/venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_qa_input.py tests/test_input_qa_postgres.py
```

No DSN means a skip; an invalid configured connection fails. Use a new `--basetemp` directory to retain reports and fixtures, and a new `--junitxml` filename for each run. Pytest can clear an existing base directory.

Regression coverage includes missing/extra locators and fields, type/empty-value differences, pagination, unavailable checks, unsupported mappings, draft official reviews and immutable evidence. Generated snapshot variants and coverage changes are also tested. The [initial](evidence/b10-b11-validation-2026-09-19.json) and [coverage-fix](evidence/b11-coverage-validation-2026-09-19.json) receipts retain their original results and hashes.

## Remaining integration

- **A:** `meta.batch`, `qa.check_result`, a valid batch and loader schema/INSERT permissions for a real `write_results` test. QA persistence, duplicate-result constraints and rollback remain unverified.
- **C and source owners:** accepted mappings and remaining semantic/location checks. The VIC amendment covers only its pinned files and restricted outputs; other official inputs still need confirmed reviews.
- **E:** consume B's per-file results and summaries through the publication gate. Real FP1, publication and the full build remain separate integration work.
