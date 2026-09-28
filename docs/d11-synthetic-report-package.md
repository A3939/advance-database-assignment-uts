# D11 — synthetic reports and demonstration package

## Fixed run

All three reports below were read through D05–D07 from one successful S0
publication. B10 executed the real A/C/D/E callbacks and E03/E06 publication in
a disposable PostgreSQL 16.15 database.

| Item | Actual value |
|---|---|
| Dataset kind | `synthetic` |
| Successful batch | `856bc5c6-a4f8-458d-8536-e9208de1ff84` |
| Input fingerprint | `a0194382d567aa6df06bac97af3c2d228c1ff58e3b14d7468ffa54a19f31ee9d` |
| Integrated B version | `562de2910bfd7be276b3036983e5680d436fde1e` |
| Raw / crash rows | 19 / 6 |
| Fatal crashes / fatalities / casualties | 2 / 3 / 7 |
| Map points | 4 of 6 (66.67%) |
| Environment | Python 3.12.14, Psycopg 3.3.6, PostgreSQL 16.15 |

The complete machine-readable return values are in the [execution receipt](evidence/d11-s0-query-results-2026-09-28.json).
The exact capture harness is retained beside it as
[`d11-report-capture.py`](evidence/d11-report-capture.py).

## Reports

1. [Trend report](reports/d11-trend-report.md) — annual and monthly D05 output.
2. [Severity report](reports/d11-severity-report.md) — populated D06 categories.
3. [Map report](reports/d11-map-report.md) — D07 points and coverage.

## Reusable demonstration

Use this order in a live or recorded demonstration:

1. Show the fixed-run table and the successful `batch_id`.
2. Open the trend report and show the five populated source/year rows, then an
   empty covered month to explain zero versus `NULL`.
3. Open the severity report and show `syn_nsw/__MISSING__` as a visible category.
4. Open the map report and show four points plus the 4/6 coverage denominator.
5. Open the JSON receipt and find the same `batch_id` under `trend`, `severity`
   and `map` to prove the reports use one version.

## Acceptance boundary

- S0 contains fictional synthetic records. These numbers are test results, not
  official road-safety statistics.
- Source-specific severity definitions remain separate even though all S0
  sources use the fictional `syn-1` definition in this run.
- A zero crash count means a covered period with no rows. A `NULL` measure means
  no known contributing value; it must not be displayed as a measured zero.
- One crash has unknown month and remains in annual/severity totals while being
  excluded from month buckets.
- Two crashes have no eligible map point. Their absence from the map does not
  remove them from crash totals.
- The run published only inside a private disposable database. It did not update
  a shared or public release. Independent E07 comparison remains an E task.
- D09 remains deferred; D11 reports use the supported query interfaces directly.
