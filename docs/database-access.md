# ARSIA database access roles

This guide describes the PostgreSQL access boundary installed by
`sql/migrations/009_database_roles.sql`.

## Role separation

| Role | Login | Intended use | Allowed | Rejected |
|---|---:|---|---|---|
| `arsia_owner` | yes | Local bootstrap and administration | Assume `arsia_migrator`; administer role passwords | Routine application use |
| `arsia_migrator` | no | Own schemas, tables and publication views | Schema and table DDL when assumed by `arsia_owner` | Direct login |
| `arsia_loader` | yes | Shared build transaction | Read/insert the 17 pipeline tables; update only batch lifecycle and release-pointer columns | Delete, truncate, schema DDL |
| `arsia_reader` | yes | Reports and UI queries | Read the seven `published.current_*` views | Base schemas, candidate batches and writes |

`arsia_migrator` is deliberately a `NOLOGIN` group role. This keeps DDL
ownership separate without storing another password. `arsia_owner` is its
administrative member and should assume it only while applying later schema
migrations.

## Local password setup

The migration never stores passwords. Set login passwords locally with the
owner account, and do not commit them to Git:

```text
psql -h 127.0.0.1 -p 55432 -U arsia_owner -d arsia -W
\password arsia_loader
\password arsia_reader
\q
```

The first `-W` prompt asks for the `arsia_owner` password. Each `\password`
command then asks twice for the new password of the named login role.

## Applying later migrations

Connect as `arsia_owner`, assume the non-login migration owner, apply the SQL,
then reset the role:

```text
SET ROLE arsia_migrator;
\i sql/migrations/<next_migration>.sql
RESET ROLE;
```

Run this from the repository root. Keep `ON_ERROR_STOP` enabled in scripted
runs so an error cannot leave a partially applied migration.

## Loader boundary

`arsia_loader` can select and insert across all 17 pipeline tables. It can
update only:

- `meta.batch.status`, `finished_at`, and `error_details`;
- `meta.current_release.batch_id`, `batch_status`, and `switched_at`.

This supports candidate registration, append-only build stages, failure
recording and atomic publication. It does not permit deletion, truncation,
schema creation or table creation.

## Reader boundary

The reader receives `USAGE` only on the `published` schema and `SELECT` only
on these security-barrier views:

- `published.current_release`
- `published.current_source`
- `published.current_severity`
- `published.current_crash`
- `published.current_unit`
- `published.current_fact_crash`
- `published.current_qa_result`

Every data view joins to `meta.current_release`. That table accepts only a
batch whose status is `succeeded`, so running, failed and unselected successful
batches remain invisible to `arsia_reader`. The reader has no `USAGE` or table
privileges on `meta`, `raw`, `rv`, `canonical`, `dw`, or `qa`.

For a page that must remain fixed until refresh, begin a read-only repeatable
read transaction, read one mode-specific row from
`published.current_release`, and use that returned `batch_id` in every page
query:

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

SELECT batch_id, switched_at
FROM published.current_release
WHERE dataset_kind = 'official';

SELECT *
FROM published.current_fact_crash
WHERE dataset_kind = 'official'
  AND batch_id = '<the batch_id returned above>';

COMMIT;
```

If no successful version is selected for that mode, the first query returns
no row and the application must report `no_publication` rather than treating
the result as a real zero.
