# D11 trend report — S0

## Query identity

- Entry point: `published.d05_trend`
- Dataset kind: `synthetic`
- Batch: `856bc5c6-a4f8-458d-8536-e9208de1ff84`
- Coverage: 2020–2024, all twelve configured months per year
- Returned rows: 15 annual and 180 monthly

## Populated annual rows

The other ten source/year rows are covered zeros.

| Source | Year | Crashes | Fatal crashes | Fatalities | Casualties |
|---|---:|---:|---:|---:|---:|
| `syn_nsw` | 2020 | 2 | 1 | 2 | 3 |
| `syn_qld` | 2020 | 1 | 0 | 0 | 1 |
| `syn_qld` | 2021 | 1 | 0 | 0 | 0 |
| `syn_vic` | 2020 | 1 | 1 | 1 | 2 |
| `syn_vic` | 2021 | 1 | 0 | 0 | 1 |
| **Total** |  | **6** | **2** | **3** | **7** |

## Month and missing-value interpretation

Of the 180 configured source/month rows, 175 have `crash_count = 0`. Their
fatal-crash, fatality and casualty measures are `NULL` when no known row
contributes; the report does not convert those unknown measures to zero.

One `syn_nsw` crash in the 2020 annual total has unknown month. D05 reports it in
the annual total, exposes the excluded-unknown-month count on monthly output,
and does not assign it to an invented month. Thus monthly crash buckets sum to
five while annual crashes sum to six.

## Limits

These are fictional S0 results under the configured synthetic coverage basis.
They demonstrate versioned trend behavior and missingness, not official trends.
See the [complete receipt](../evidence/d11-s0-query-results-2026-09-28.json) for
every annual and monthly row.
