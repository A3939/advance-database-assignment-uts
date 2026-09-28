# D11 map report — S0

## Query identity

- Entry point: `published.d07_map`
- Dataset kind: `synthetic`
- Batch: `856bc5c6-a4f8-458d-8536-e9208de1ff84`
- Filter: 2020–2024, all sources and months

## Coverage

| Measure | Actual result |
|---|---:|
| All crashes | 6 |
| Eligible points | 4 |
| Unmapped crashes | 2 |
| Coverage | 66.67% |

## Returned points

| Source | Crash key | Year-month | Severity | Latitude | Longitude |
|---|---|---|---|---:|---:|
| `syn_nsw` | `["0001"]` | 2020-01 | `F` | -33.8600000 | 151.2000000 |
| `syn_qld` | `["0001"]` | 2020-01 | `I` | -27.4700000 | 153.0200000 |
| `syn_qld` | `["0002"]` | 2021-02 | `N` | -27.5000000 | 153.0500000 |
| `syn_vic` | `["0001"]` | 2020-01 | `F` | -37.8000000 | 144.9000000 |

Each point retains the same batch, source, release scope and crash key used by
the fact query. The two unmapped crashes remain in the six-crash denominator;
the map never interprets missing or ineligible coordinates as absence of a
crash. Coordinates are synthetic EPSG:4326 test values.

## Limits

The 4/6 result is S0 acceptance evidence only. It must not be presented as
official geographic coverage. See the [complete receipt](../evidence/d11-s0-query-results-2026-09-28.json)
for coverage metadata and exact machine-readable point rows.
