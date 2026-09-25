# B08 PostgreSQL reproduction — 20 September 2026

**8 passed, 0 skipped, 0 failed** in 0.41 seconds, using a real `arsia_loader` connection. This reproduces JJ's B08 result on this machine.

## Versions and isolation

JJ's [handoff](https://github.com/A3939/advance-database-assignment-uts/blob/1b257c831c665e1c8d38ca7b6b0d2f8ed02afed1/docs/b08-db-handoff.md) was read from `jj/a01-environment` at `1b257c8`. Its three migration hashes match the document. JJ's Raw loader and eight PostgreSQL tests are byte-identical to `peixian/dev` at `cbb548e`.

The run used JJ's unchanged Compose image and settings: PostgreSQL **16.15**, UTF8, UTC and `C.UTF-8`, with Python **3.12.6** and Psycopg/psycopg-binary **3.3.6**. The image digest is recorded in the [validation receipt](evidence/b08-postgres-validation-2026-09-20.json).

A new Compose project, container and data volume kept this test separate from existing databases. The database name stayed `arsia` so all three migrations ran unchanged. Its loopback port was `56697`, replacing JJ's example port `55432`. Test dependencies were installed in a separate environment under `artifacts/`; the existing `.venv` was not changed. JJ's branch was fetched and selected files exported, without merging it.

## What was checked

- The live catalog contains the three B08 tables, 16 columns, two foreign keys and the contracted indexes/checks. Raw identity is unique and non-deferrable; its resource/source pair uses the composite foreign key.
- `arsia_loader` is not a superuser, database/role creator, replication user, table owner or member of another role, and cannot bypass row security. It has schema USAGE and table SELECT/INSERT, without schema CREATE or table UPDATE/DELETE/TRUNCATE/REFERENCES/TRIGGER.
- Six real UPDATE/DELETE attempts, covering all three tables, were rejected with SQLSTATE `42501`. A source INSERT succeeded and was rolled back.
- The eight unchanged tests verified S0's 3 sources, 7 resources and 19 lossless Raw rows; UUID/timestamp reuse; payload and registration conflicts; synthetic/official separation; caller rollback; autocommit rejection; and distinct identities after file/parser changes.
- After the tests, `meta.source`, `meta.resource` and `raw.record` each contained zero rows. Every test write was rolled back.

## Reproduction and evidence

The local run is under `artifacts/b08-db-reproduction-2026-09-20/`. It contains the exported JJ files, catalog audit, pytest output and JUnit report. A protected local passfile supplies the password; no password is included in the shared receipt.

The executed test command, with paths shortened to the repository root, was:

```sh
ARSIA_TEST_DSN='host=127.0.0.1 port=56697 dbname=arsia user=arsia_loader' \
PGPASSFILE="$PWD/artifacts/b08-db-reproduction-2026-09-20/private/pgpass" \
PYTHONDONTWRITEBYTECODE=1 \
artifacts/b08-db-reproduction-2026-09-20/venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_raw_load_postgres.py \
  --junitxml artifacts/b08-db-reproduction-2026-09-20/pytest.xml
```

The test container `arsia-b08-20260920-e4d6b07f-db` was stopped after verification. Its separate volume was retained. To run it again, start that container, check its mapped port and choose a new report filename. For a fresh database, follow JJ's pinned handoff and apply migrations once.

## B08 conclusion

The current B08 task criteria are met by this local integration run: source/resource registration, Raw ID reuse and rejection of a changed payload under the same identity. No B08 migration or loader defect was found.

This does not establish durable commits, concurrency, official-data loading, the full AT02/build, reader permissions or the remaining 14 tables. The rollback-only test database is not a shared Raw dataset for C. Those are separate integration steps; B09–B14 and official source approval are unchanged.
