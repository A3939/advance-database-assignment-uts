# A03 database-role validation — 23 September 2026

## Scope

Validated `sql/migrations/009_database_roles.sql` against PostgreSQL 16.15.
The reproducible rollback test is `sql/tests/a03_database_roles.sql`.
The migration separates schema ownership, pipeline loading and published-data
reading while retaining the 17-table A02 physical model.

## Installed boundary

- `arsia_migrator` is a non-login owner of all seven database schemas and all
  17 physical tables.
- `arsia_owner` is an administrative member of `arsia_migrator`.
- `arsia_loader` has `SELECT` and `INSERT` on all 17 physical tables, plus
  column-scoped lifecycle updates. It has no `DELETE` or schema DDL access.
- `arsia_reader` has no base-schema usage and no base-table `SELECT` access.
- `arsia_reader` has `SELECT` on seven security-barrier
  `published.current_*` views.
- Each published data view is restricted by `meta.current_release`, whose
  foreign key and check constraint permit only `succeeded` batch pointers.

## Local behavioural test

A rollback-only fixture created one selected successful batch and one running
candidate batch, with one QA row in each.

Observed results:

- reader saw exactly one published QA row;
- reader saw zero rows from the candidate batch;
- direct reader access to `meta.batch` was rejected;
- reader update of a published view was rejected;
- loader insert and batch-state update succeeded;
- loader delete and schema DDL were rejected;
- final fixture-residue count was zero.

## Privilege audit

| Check | Result |
|---|---:|
| Physical tables | 17 |
| Physical tables owned by `arsia_migrator` | 17 |
| Tables with loader `SELECT` + `INSERT` | 17 |
| Tables with loader `DELETE` | 0 |
| Base tables readable by reader | 0 |
| Published views readable by reader | 7 |
| Reader usage on `published` | yes |
| Reader usage on `meta` | no |
| Owner membership in migrator | yes |

All seven views recorded both `security_barrier=true` and
`security_invoker=false`.

## Cold-start replay

An isolated container using the pinned PostgreSQL 16 image applied migrations
`001` through `009` in filename order. The replay produced 17 physical tables
and seven published views. The same rollback-only permission test passed. The
temporary container was then removed.

## Limits

- Login passwords are intentionally absent from version control and must be
  assigned locally or by a deployment secret manager.
- A03 supplies the access boundary; page queries must still bind one returned
  `dataset_kind` and `batch_id` for the duration of a page transaction.
- A03 does not publish an official or synthetic batch and does not replace the
  independent QA/publication gate.
