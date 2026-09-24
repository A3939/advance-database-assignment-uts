# D08 basic-unit query

`arsia_d08.query_units(...)` reads Canonical unit details from one explicit
successful batch. It applies source, year and month filters through each
unit's complete parent-crash identity and returns eligible counts grouped by:

- source;
- the source-defined `statistical_scope`; and
- the source-defined `unit_type_code`.

Only `canonical.unit.count_eligible=true` rows contribute. The query does not
create a unit warehouse table, expand QLD crash-row category counts into unit
details, or aggregate crash measures after joining units. NSW traffic units
and VIC vehicles therefore remain in separate source and statistical scopes.

## Deployment and use

Deploy `src/arsia_d08/sql/d08_units.sql` as `arsia_migrator` after migrations
001-011. It installs the versioned read-only function:

`published.d08_unit_counts(text,uuid,text[],integer,integer,integer[])`

The function requires a successful batch whose dataset mode matches the
request. It has a fixed `pg_catalog` search path, exposes execution to
`arsia_reader` and the existing build/test loader, and leaves transaction
ownership with the caller.

```python
from arsia_d08 import UnitRequest, query_units

rows = query_units(
    connection,
    UnitRequest("synthetic", batch_id, source_ids=("syn_nsw",)),
)
```

An empty filtered period or a source with no real unit details returns an
empty tuple. It does not return an invented zero row with an invented type or
scope.

## Validation scope

The interface and SQL-contract tests cover fixed-batch arguments, result
shape, complete parent identity, eligibility, grouping boundaries, packaged
SQL and permissions. PostgreSQL 16 cases exercise the real C09 to D03 path,
source-defined NSW counts, ineligible rows, parent time filters, empty
periods, unsuccessful batches, mode mismatches and unknown sources.

Final acceptance on 2026-09-25 produced:

- 24 passed, 0 failed and 0 skipped in the focused D08 PostgreSQL 16 run;
- 156 passed, 0 failed and 0 skipped in the temporary A/B/C/D integration
  overlay; and
- three eligible NSW units under `synthetic_traffic_unit`, three eligible VIC
  units under `synthetic_vehicle`, no QLD unit-detail rows and an unchanged
  six-row crash fact table for the full S0 fixture.

Focused evidence is in
`docs/evidence/d08-postgres-validation-2026-09-25/`. Integration evidence is
in `docs/evidence/d08-c45-postgres-validation-2026-09-25/`; its input file
records C commit `ad8baeddd3f6d2eeccdc2e31bafd71b687ad4da8`, the earlier D
integration inputs and D08 commit
`8df3b0c66bcd2eceb1fac394a2a795f8a3879f03`. The integration run used a
local, hash-recorded overlay and did not publish or copy C's implementation
into this branch.
