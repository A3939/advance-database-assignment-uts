# D11 severity report — S0

## Query identity

- Entry point: `published.d06_severity`
- Dataset kind: `synthetic`
- Batch: `856bc5c6-a4f8-458d-8536-e9208de1ff84`
- Filter: 2020–2024, all months
- Definition version: `syn-1` per source

## Actual populated categories

| Source | Code | Label | Crash count |
|---|---|---|---:|
| `syn_nsw` | `F` | Fatal | 1 |
| `syn_nsw` | `__MISSING__` | Unknown | 1 |
| `syn_qld` | `I` | Injury | 1 |
| `syn_qld` | `N` | Non-injury | 1 |
| `syn_vic` | `F` | Fatal | 1 |
| `syn_vic` | `I` | Injury | 1 |
| **Total** |  |  | **6** |

The query returns populated categories only. `__MISSING__` is an explicit source
category and remains visible; it is not silently mapped to non-injury or zero.
The configured fictional rule maps only `F`, `I` and `N` directly and blocks any
other nonempty native value.

## Limits

Even when labels look similar, severity rows retain `source_id` and
`definition_version`. Cross-source pooling requires an approved harmonisation
rule and is outside this report. These are synthetic classifications, not
official NSW, QLD or VIC severity definitions. The exact definitions and rows
are retained in the [execution receipt](../evidence/d11-s0-query-results-2026-09-28.json).
