# D09 local dashboard and fixed-release reads

D09 provides one server-rendered local page over the existing D05-D08
queries. At the start of each page request it reads
`published.current_release` once, captures that successful `batch_id`, then
passes the same ID to trend, severity, map and unit queries. A pointer switch
during the request cannot mix versions.

The page displays:

- dataset mode, pinned batch and pointer time;
- frozen source and release labels for that batch;
- selected source, year, month and trend-grain filters;
- trend values, severity definitions and counts;
- map points and the SQL-calculated coverage value; and
- source-scoped eligible unit counts.

SQL `NULL` and zero remain distinct. The page renders values returned by the
queries and does not recalculate coverage or business metrics in the browser.

## Start the page

Fixed example mode requires no database and is visibly labelled as
illustrative:

```powershell
python -m arsia_d09 --demo
```

For a real published release, install the database requirements and provide a
read-only `arsia_reader` connection:

```powershell
$env:ARSIA_READER_DSN = 'postgresql://arsia_reader:...@localhost:5432/arsia'
python -m arsia_d09
```

Open `http://127.0.0.1:8765/`. The server binds to localhost by default. It
adds no JSON API or authentication layer and sends `Cache-Control: no-store`.

## Deployment

Deploy D05-D08 SQL and then `src/arsia_d09/sql/d09_context.sql` as
`arsia_migrator`. D09's helper function exposes fixed-batch source/release
labels to `arsia_reader` without granting that role access to internal
schemas.

## Implemented validation

The test suite covers strict page parameters, no-publication output, HTML
escaping, NULL/zero display, demo HTTP startup, read-only database access and
all D05-D08 components returning the same batch. PostgreSQL acceptance also
pins one release, changes `current_release` to another successful batch, and
confirms that the already-started page read continues to use the first batch.

The recorded 2026-09-25 PostgreSQL 16 run passed 19 tests with 0 failures,
0 errors and 0 skips. It used D09 implementation commit
`d468cec2392a10a10b83c2ae8d6a5caac0516995`, exercised the actual
`arsia_reader` role, and published no release outside its disposable test
database. Reproduction logs and exact inputs are in
`docs/evidence/d09-postgres-validation-2026-09-25/`. The rendered fixed-example
page and visual-check screenshot are in
`docs/evidence/d09-ui-preview-2026-09-25/`.

## Remaining team acceptance

The independent test creates controlled successful batches because the shared
B/E publication path is not complete. Final D09 acceptance still needs a real
B10 build published by E06, followed by the same mid-read pointer-switch check
against that build. Until that happens, D09 remains in progress even when its
implementation and isolated PostgreSQL tests pass.
