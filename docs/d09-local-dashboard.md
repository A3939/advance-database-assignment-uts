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
labels and manifest year bounds to `arsia_reader` without granting that role access to internal
schemas.

For d09-0.1.1, redeploy this SQL before restarting the page. The new
`published.d09_batch_years(text, uuid)` function checks the pinned batch,
not the current pointer. Page years must stay inside that batch's analysis
range. D05 can still query uncovered years directly.

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

## Real B10/E06 acceptance

Final D09 acceptance was completed on 2026-09-28 from the current integrated
backend at `peixian/dev` commit
`562de2910bfd7be276b3036983e5680d436fde1e`. The installed Python 3.12 package
ran in a disposable PostgreSQL 16.15 database and passed 17 tests with zero
failures, errors or skips.

The acceptance used the real B10 runner and E06 publisher twice. The first S0
publication produced six crashes and six eligible units. D09 pinned that batch,
then a second B10/E06 build published a 2021-2024 release. Every query on the
already-started page continued to return only the first batch; a refreshed page
resolved the second batch and returned its two in-scope crashes. The rendered
HTML displayed each pinned batch ID. Tests ran as `arsia_reader`, the A03 audit
passed before and after, all database tables were empty after cleanup and the
container was removed.

The exact command, inputs, hashes, JUnit output, compact B10/E06 publication
result receipts and cleanup receipt are in
`docs/evidence/d09-full-build-validation-2026-09-28/`. These were private
synthetic publications inside the disposable test database; no public or shared
release was created. E07's independent platform acceptance remains a separate
team task and does not change D09's completed implementation acceptance.

## PR #43 review fixes

The d09-0.1.1 follow-up adds readable HTTP errors, pinned year limits and
known-count columns. It also fixes default test collection without psycopg
and keeps the dashboard separate from required build callbacks.
See [the follow-up tests and deployment notes](d09-review-fixes.md).
The earlier evidence above records the original D09 version.

## Export a PDF report

Load the desired release and filters, then select **Print / Save as PDF**.
Choose **Save as PDF** in your browser's print dialog. The report uses an A4
landscape layout with wrapping tables and repeating column headers. It includes
applied filters, batch identity, source releases, all result sections and quality
notes. NULL, zero and unavailable reports remain distinct; illustrative demo
reports retain their warning.

Export prints the already displayed snapshot without querying the database again.
After editing filters, select **Read fixed release** before exporting; unapplied
form edits do not change the report's applied-filter summary. Browser print
(Ctrl+P or Cmd+P) also works. Disable browser-added headers and footers if desired.
This is browser-based PDF export, not a server-side PDF download endpoint.
