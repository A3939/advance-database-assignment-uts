# B08: source registration and Raw loading

[`raw_load.py`](../src/arsia_ingest/raw_load.py) follows team v1.1 [02, database fields](../../F/ARSIA-Team-Handoff/02-数据库字段字典.md), [04, L1 contract](../../F/ARSIA-Team-Handoff/04-团队分工与验收.md) and [05, native identities](../../F/ARSIA-Team-Handoff/05-来源与映射说明.md). The F/ links require the shared course workspace.

Synthetic loading passed against A's PostgreSQL 16 migrations and loader permissions in the [2026-09-20 reproduction](b08-postgres-review.md). All test writes were rolled back; no shared Raw dataset was created. Old setup files and unexecuted reference SQL were not used.

## What it writes

| Table | Input |
|---|---|
| `meta.source` | `source_id`, `jurisdiction_code`, `source_name`, `publisher` |
| `meta.resource` | `resource_id`, `source_id`, `resource_role`, `entity_kind` from each selected file |
| `raw.record` | Six L1 members and a new UUID. PostgreSQL supplies `ingested_at`. |

Identical registrations are reused. Changed source metadata or resource owner/role/kind raises `REGISTRATION_CONFLICT`. This is an implementation choice: the team contract leaves metadata editing undefined. Reviewed changes can be handled separately without rewriting Raw history.

Raw identity is `(resource_id, file_sha256, parser_version, row_locator)`; source consistency is also checked. Matching identity and JSONB payload return the existing UUID with `inserted=False`. A different payload raises `RAW_PAYLOAD_CONFLICT`. Existing payloads, UUIDs and first-ingest timestamps stay unchanged.

Payloads must contain exactly the native columns, with text or NULL values. Empty strings, whitespace, leading zeros, categories and locator text are preserved. There is no business cleaning, year filtering, Node deduplication, QLD count expansion or business-key creation. Identical payloads at different positions remain separate records.

IDs retain the `official_`/`syn_` separation. Jurisdictions and resource counts are configurable. Supply source metadata explicitly; optional `resource_ids` must match the selected files. S0 source definitions are in [`contract.json`](../tests/fixtures/s0/contract.json).

## Connection and transactions

Supply a PostgreSQL 16 DB-API connection using UTF-8, UTC, `autocommit=False`, `%s` parameters and default tuple cursor rows. The loader opens cursors only; the caller owns the connection, commit, rollback and close. It creates no tables or server functions.

Inserts use `INSERT ... ON CONFLICT DO NOTHING RETURNING raw_record_id`. A conflict triggers a separate `SELECT` to compare the stored source and JSONB payload. This allows a fresh READ COMMITTED snapshot after a competing insert; see PostgreSQL's [INSERT rules](https://www.postgresql.org/docs/16/sql-insert.html) and [transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html). Only SELECT/INSERT permissions are needed.

**The caller must roll back the whole load, including registration, after any exception.** Input and callback errors may leave earlier writes pending because Python validation errors do not abort PostgreSQL transactions. Database errors propagate without internal retries.

Under 04, B commits Raw/registration in a short transaction before the business build. [B10's runner](runner.md) owns the shared connection, session lock `(32113, 2)` and lifecycle. It stops on uncertain commits; [B14 recovery](recovery.md) is a separate step with real validation pending. B08's return value describes pending writes, not a commit, QA pass, `no_change` or publication.

## Loading prepared input

Prepare the checked-in S0 files:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m arsia_ingest \
  --config tests/fixtures/s0/config.json --output artifacts/s0-intake
```

Pass the returned `run_dir` and B's supplied connection:

```python
import json
from pathlib import Path
from arsia_ingest.raw_load import load_prepared

sources = json.loads(Path("tests/fixtures/s0/contract.json").read_text())["sources"]
try:
    result = load_prepared(connection, run_dir, sources)
except BaseException:
    connection.rollback()
    raise
# The caller owns the commit.
```

`load_prepared(connection, run_dir, sources, *, on_record=None)` returns `RawLoadResult`: `run_id`, `dataset_kind`, `raw_count`, `inserted_count` and `reused_count`. The optional callback receives `(l1_record, RawRecordResult)`, including `raw_record_id` and `inserted`, for each accepted row. Callback failures stop the load.

Keep the complete output tree, including archives. Relocated runs use relative paths rather than old absolute receipt paths. Before registration, the loader checks `prepared` status, file lists, metadata, archive hashes and JSONL hashes. It streams JSONL to check the six L1 members, native columns, locator order, row counts and stream hash. Incomplete runs or changed records/archives are rejected without loading whole JSONL files into memory.

Raw's source/resource/hash/parser/locator fields preserve row lineage. `provenance.json` connects file hashes to archives and input names; archives and receipts remain unchanged. B09's full manifest still needs download URLs, evidence references and frozen release semantics. `files.json` is only its file fragment.

For an existing L1 stream:

```python
from arsia_ingest.raw_load import RawLoader

loader = RawLoader(connection, dataset_kind="synthetic", sources=sources, files=files)
loader.register()
accepted = loader.load_record(l1_record)
```

`files` uses the existing 13-member `files[]` format. This interface validates individual rows, not archive integrity, file completeness or stream counts. Use one loader per caller-managed unit of work.

Known VIC issues can be preserved in Raw for review. Official business QA and publication still require the draft-contract and compatibility checks.

## Tests and remaining setup

Run the full suite:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

The 2026-09-18 run recorded **184 passed, 8 skipped**, including 31 B08 tests in [`test_raw_load.py`](../tests/test_raw_load.py). Scripted query replies test validation, parameter binding, IDs, conflicts and connection ownership across all 19 S0 records. They do not verify PostgreSQL SQL, constraints or transactions.

All eight PostgreSQL tests were skipped because no test connection was supplied. The [receipt](evidence/b08-validation-2026-09-18.json) records the command, hashes and outstanding checks. It is unchanged; its hash for this guide predates this wording edit.

The [2026-09-20 reproduction](b08-postgres-review.md) verified JJ's three migrations and loader permissions: **8 passed, 0 skipped, 0 failed**. Use a migrated **test database**, the agreed Psycopg 3 environment and `ARSIA_TEST_DSN` for these checks:

```sh
PYTHONDONTWRITEBYTECODE=1 \
artifacts/b08-db-reproduction-2026-09-20/venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_raw_load_postgres.py
```

Without the variable, [these tests](../tests/test_raw_load_postgres.py) skip before importing the driver. With it, driver, connection, PostgreSQL version/encoding/time-zone, table or permission problems fail the tests. They use unique synthetic namespaces, create no schema and roll back writes. Coverage includes the 19-row S0 load, UUID/timestamp reuse, payload/registration conflicts, namespace isolation and caller rollback. Concurrency, durable commits and platform acceptance remain unverified.

The local test environment now has PostgreSQL 16, the pinned driver, all three B08 tables and loader USAGE/SELECT/INSERT grants. See the reproduction guide for versions and evidence; the original `.venv` is unchanged.

All seven S0 resources are available as native/prepared input, **not shared database rows**. B08 and [B11's native-to-Raw checks](input-qa.md) have passed with real PostgreSQL, but tests rolled back every write. A persistent shared Raw load for C, QA result persistence and publication still need integration.
