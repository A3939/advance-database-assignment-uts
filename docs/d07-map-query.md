# D07 map points and coverage query

`arsia_d07.query_map(...)` binds one successful batch and one set of optional
source, year and month filters. It returns:

- one point row for every eligible crash identity; and
- one SQL-calculated coverage row for the same filters.

The point identity is `batch_id + source_id + release_scope + crash_key`.
Coordinates are never grouped, so two crashes at the same latitude and
longitude remain two rows. Only facts with `map_eligible=true` and non-NULL
coordinates appear as points.

Coverage uses every fact selected by the filters as its denominator. It
returns `crash_count`, `point_count` and a percentage rounded to two decimal
places. An empty denominator returns counts of zero and a NULL percentage.
Month filtering excludes facts whose month is unknown.

## Deployment and use

Deploy `src/arsia_d07/sql/d07_map.sql` as `arsia_migrator` after migrations
001-011. The deployment installs two versioned read-only functions:

- `published.d07_map_points(...)`;
- `published.d07_map_coverage(...)`.

Both require an explicit successful batch whose dataset mode matches the
request. They use a fixed `pg_catalog` search path, expose execution only to
`arsia_reader` and the existing build/test loader, and do not own transaction
lifecycle.

```python
from arsia_d07 import MapRequest, query_map

result = query_map(
    connection,
    MapRequest("synthetic", batch_id, source_ids=("syn_nsw",)),
)
```

`result.points` contains the map rows. `result.coverage` contains the matching
denominator, point count and percentage.

## Validation scope

The unit and contract tests cover arguments, fixed result shapes, packaged
SQL, permissions, batch/mode guards, identity-preserving point selection and
SQL coverage calculation. PostgreSQL 16 cases exercise the current real
C09 -> D03 path, identical-coordinate identities, exact month denominators,
empty periods and invalid batch/source requests.
