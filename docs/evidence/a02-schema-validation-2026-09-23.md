# A02 schema validation — 23 September 2026

## Scope

This receipt covers Role A task A02 only: the 17 shared PostgreSQL tables,
their 129 fields, 30 foreign keys, declared constraints, indexes, comments and
schema migration order. It does not claim that an official build, source
projection, QA gate or publication has completed.

## Environment

- PostgreSQL: `16.15 (Debian 16.15-1.pgdg12+2)`
- Encoding: `UTF8`
- Time zone: `UTC`
- Database schemas: `meta`, `raw`, `rv`, `canonical`, `dw`, `qa`

## Ordered A02 migrations

The schema was replayed into a new empty temporary database in this order:

1. `sql/migrations/001_meta_registry.sql`
2. `sql/migrations/002_raw_record.sql`
3. `sql/migrations/004_meta_batch.sql`
4. `sql/migrations/005_raw_vault.sql`
5. `sql/migrations/006_canonical.sql`
6. `sql/migrations/007_warehouse.sql`
7. `sql/migrations/008_qa.sql`

`003_b08_loader_role.sql` belongs to A03 permissions and creates a
cluster-level role, so it was not required to count or order the A02 tables.

The clean replay completed without manual repair and returned:

| Check | Observed | Required |
|---|---:|---:|
| Tables | 17 | 17 |
| Fields | 129 | 129 |
| Foreign keys | 30 | 30 |
| Commented tables | 17 | 17 |
| Commented fields | 129 | 129 |

The temporary database was removed after verification.

## Required additional indexes

All seven declared non-PK/non-UNIQUE indexes were present:

- `raw.raw_file_idx`
- `meta.batch_fingerprint_idx`
- `rv.link_parent_idx`
- `canonical.crash_year_idx`
- `canonical.unit_parent_idx`
- `dw.fact_trend_idx`
- `qa.qa_result_idx`

## Transactional behaviour checks

A rollback-only test created one complete temporary chain from source and Raw
through Vault, Canonical, Warehouse and QA. The valid chain produced one
Canonical crash, one Canonical unit, one fact and one QA result.

PostgreSQL constraints rejected all of these invalid changes:

- a fabricated day on a month-precision crash;
- `map_eligible=true` without coordinates, CRS and location lineage;
- an eligible fatality metric with a NULL fatality count;
- an eligible unit with a NULL analytical type code;
- a fact month whose year differed from `occurrence_year`;
- a blocking QA result with empty evidence.

The test transaction rolled back. Follow-up checks found zero temporary source
rows, zero temporary batches and no remaining verification database.

## Official-data decision boundaries

The shared schema supports both official and synthetic batches. Current team
decisions are enforced by projections, manifests, QA and permissions in
addition to these structural constraints:

- first-version official NSW, VIC and QLD maps remain disabled;
- synthetic map eligibility remains supported;
- source-specific severity and metric definitions must not be pooled;
- QLD aggregate unit counts do not create Canonical unit rows;
- current restricted VIC unit projections are not enabled as unit KPIs;
- official and synthetic releases remain separate.

These schema checks do not prove official source activation, full-input QA,
publication, performance, WAL/disk measurements or recovery acceptance.
