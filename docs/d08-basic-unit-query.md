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

The complete three-source S0 acceptance must also verify three eligible NSW
units, three eligible VIC units and no QLD unit-detail rows using the current
C04/C05 integration overlay. That validation is recorded separately so this
branch does not copy or claim C's implementation.
