# D05 L5 trend query

`published.d05_trend(...)` is the versioned Role D trend entry point. It reads
only a caller-selected successful batch, aggregates `dw.fact_crash`, and uses
the frozen crash-resource coverage in `meta.batch.manifest`. It does not read
or recalculate Raw, Vault, Canonical, eligibility, or source semantics.

## Deployment and reader boundary

Deploy `src/arsia_d05/sql/d05_trend.sql` as a member of
`arsia_migrator` after migrations 001–011. The script fixes the function owner
to `arsia_migrator`, removes PUBLIC execution, and grants only `arsia_reader`
and the existing build/test loader access. The function is `STABLE`, has a
fixed `pg_catalog` search path, and owns no transaction lifecycle.

The security-definer boundary is required because readers cannot select
`meta.batch` or `dw.fact_crash` directly. It exposes only aggregates from a
batch whose stored status is `succeeded` and whose `dataset_kind` equals the
requested mode. Passing an explicit batch keeps all page queries on the same
version if `meta.current_release` changes before a page refresh.

## L5 call

```sql
SELECT *
FROM published.d05_trend(
    'synthetic',                         -- dataset_kind
    '00000000-0000-0000-0000-000000000001'::uuid,
    'year',                              -- year | month
    ARRAY['syn_nsw']::text[],            -- NULL means all enabled sources
    2020,
    2024,
    NULL                                 -- NULL means all 12 months
);
```

Python callers use `arsia_d05.query_trend(connection, TrendRequest(...))`.
The database validates the batch mode/status and every L5 argument again.

Each row returns the mode, batch, source, grain, year/month, coverage status,
requested/covered month counts, coverage basis, crash count,
`month_known_count`, excluded unknown-month count, and the fatal-crash,
fatality and casualty values with their independent known counts.

## NULL, zero, month and coverage rules

- An unfiltered annual row includes crashes whose `month_id` is NULL.
- Monthly rows and annual rows with a month filter exclude unknown months and
  report them in `excluded_unknown_month_count`.
- A declared covered period with no crashes returns `crash_count = 0`.
- A measure is NULL when its eligibility-specific known count is zero. A
  known eligible sum or count of zero remains numeric zero.
- An uncovered period returns `coverage_status = not_covered` and NULL
  metrics. Partially covered annual selections are marked `partial`.
- Sources remain separate. Fatal crashes, fatalities and casualties use their
  own fields and eligibility flags.

## Validation boundary

`tests/test_d05.py` checks the fixed interface, input rejection, packaged SQL,
successful-batch guard, frozen coverage source, aggregation fields, grants and
absence of Raw/Canonical reads or transaction control. The opt-in
`tests/test_d05_postgres.py` runs the actual C09 → D03 → D05 path and checks:

1. 15 S0 annual source-year rows, including a covered empty year;
2. annual retention and monthly exclusion of an unknown-month crash;
3. explicit disclosure for a month-filtered annual query; and
4. NULL metrics for an uncovered year; and
5. an unknown-only measure case with zero known counts and NULL values.

Those cases require PostgreSQL 16, `ARSIA_TEST_DSN`, and the deployed D05 SQL.
Skipping them is not database acceptance. Full VIC/QLD results additionally
depend on B integrating the completed C04/C05 and D03 callbacks and E
publishing a successful batch.
