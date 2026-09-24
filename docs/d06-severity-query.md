# D06 L5 severity query

`published.d06_severity(...)` is the versioned Role D severity entry point. It
groups a caller-selected successful batch by the complete source-specific
definition identity:

```text
source_id + definition_version + severity_code
```

Labels, definition versions and definition text come from the selected
batch's `dw.dim_severity`; counts come from `dw.fact_crash`. The query never
reclassifies values, combines equal codes across sources, or reads Raw,
Vault, Canonical or native files.

## Deployment and L5 call

Deploy `src/arsia_d06/sql/d06_severity.sql` as a member of
`arsia_migrator` after migrations 001–011. The security-definer function has
a fixed `pg_catalog` search path, is owned by `arsia_migrator`, removes PUBLIC
execution, and grants execution to `arsia_reader` and the existing build/test
loader. It accepts only a stored `succeeded` batch matching the requested
`dataset_kind` and owns no transaction lifecycle.

```sql
SELECT *
FROM published.d06_severity(
    'synthetic',
    '00000000-0000-0000-0000-000000000001'::uuid,
    ARRAY['syn_nsw']::text[], -- NULL means all enabled sources
    2020,
    2024,
    NULL                     -- NULL means all months
);
```

Python callers use
`arsia_d06.query_severity(connection, SeverityRequest(...))`. The fixed return
shape contains the mode, batch, source, effective year/month filters, frozen
definition version, code, label, definition text and `crash_count`.

Only populated groups are returned. `__MISSING__` remains an ordinary explicit
frozen category when facts use it. A month filter excludes year-only facts
because their `month_id` is NULL. Group counts therefore reconcile to the fact
count under the exact same source/year/month filter.

## Validation boundary

`tests/test_d06.py` checks argument rejection, fixed output shape, packaging,
inventory hashes, successful-batch/mode guards, complete source-specific join
keys, grouping fields, permissions and absence of transaction control or
Raw/Canonical reads.

The opt-in `tests/test_d06_postgres.py` checks the current real NSW C09 → D03
path: populated `F` and `__MISSING__` groups, exact labels/versions/text,
group-count reconciliation, unknown-month exclusion, and rejection of running
or wrong-mode batches. It requires PostgreSQL 16, `ARSIA_TEST_DSN`, and the
deployed D06 SQL.

The complete S0 acceptance target is six populated source/category groups in
one successful batch. That final result remains pending B's integration of
C04/C05 and D03 plus E's publication step; the code and tests do not claim it
from the current NSW-only integration path.
