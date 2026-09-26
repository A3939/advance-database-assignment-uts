# NSW Crash and Traffic Unit source model and query evidence

## Scope

This A08 evidence describes the selected NSW Crash and Traffic Unit native
resources and reports the results of executable PostgreSQL queries. It is tied
to the exact files below and does not confirm a different download or release.

| Resource | Sheet | Rows | SHA-256 |
|---|---:|---:|---|
| NSW Crash 2020–2024 | `Sheet1` | 92,189 | `7345189f017d9c842429674ecf2196cee728de46c0572ce2a85220f9bef49aa9` |
| NSW Traffic Unit 2020–2024 | `Export` | 170,962 | `95349666f63952c580edb08973a8ac80be39db98ba289ec8533d61feb6d55f1b` |

The intake output contained 263,151 records. Both prepared JSONL streams were
independently checked for line count and SHA-256 before the database run.

## Native source model

```text
NSW Crash                                      NSW Traffic Unit
────────────────────────────────────           ──────────────────────────────
PK  Crash ID                         1 ─────<   PK/FK  Crash ID
                                                   PK  Traffic unit ID
    Reporting year                                  TU type group
    Year of crash                                   other native attributes
    Month of crash
    No. of traffic units involved
    other native attributes
```

The native grains and relationships are:

| Resource | Native grain | Shared encoded key |
|---|---|---|
| Crash | one row per `Crash ID` | `rv.encode_business_key(Crash ID)` |
| Traffic Unit | one row per (`Crash ID`, `Traffic unit ID`) | `rv.encode_business_key(Crash ID, Traffic unit ID)` |
| Parent relationship | Unit `Crash ID` references Crash `Crash ID` in the same selected snapshot | the Unit key retains the complete parent component |

`Traffic unit ID` is not treated as globally unique. The parent Crash must be
resolved against the complete selected Crash file before applying the
2020–2024 occurrence-year filter.

## Executed query results

The commented query package is
[`sql/evidence/a08_nsw_source_queries.sql`](../../sql/evidence/a08_nsw_source_queries.sql).
The machine-readable results are
[`evidence/nsw/a08-nsw-query-results-2026-09-26.json`](evidence/nsw/a08-nsw-query-results-2026-09-26.json).

### Selected rows

| Resource | Actual | Expected | Difference |
|---|---:|---:|---:|
| Crash | 92,189 | 92,189 | 0 |
| Traffic Unit | 170,962 | 170,962 | 0 |

### Key and relationship checks

| Check | Result |
|---|---:|
| Blank Crash keys | 0 |
| Duplicate Crash-key groups | 0 |
| Blank Traffic Unit composite keys | 0 |
| Duplicate Traffic Unit composite-key groups | 0 |
| Traffic Unit rows without a parent Crash | 0 |

All 92,189 Crash rows had a numeric declared traffic-unit count. The sum of
the declarations was 170,962, the observed child-row total was 170,962, and
the per-Crash mismatch count was zero. This reconciliation applies only to the
exact selected pair and does not establish compatibility for another release.

### Occurrence and reporting years

| Year | Occurrence-year Crash rows | Reporting-year Crash rows |
|---:|---:|---:|
| 2019 | 107 | 0 |
| 2020 | 18,764 | 18,704 |
| 2021 | 17,413 | 17,517 |
| 2022 | 18,255 | 18,245 |
| 2023 | 18,711 | 18,706 |
| 2024 | 18,939 | 19,017 |

There were 488 rows where `Reporting year` and `Year of crash` differed.
Occurrence analysis therefore uses `Year of crash`; `Reporting year` remains
an audit attribute and must not substitute for occurrence time.

### Analysis scope

| Measure | Result |
|---|---:|
| 2020–2024 Crash rows | 92,082 |
| Units whose parent Crash occurred in 2020–2024 | 170,747 |
| Raw-only 2019 Crash rows | 107 |
| Units whose parent Crash occurred in 2019 | 215 |
| Covered 2020–2024 year-month combinations | 60 |

The 2019 rows remain in Raw for lineage and relationship validation. They are
not silently deleted and are not included in the 2020–2024 analysis counts.

### Real relationship example

For native Crash `1215855`, the executed query returned three child Traffic
Units with IDs `1`, `2` and `3`. Their shared encodings were:

```text
Crash: ["1215855"]
Unit 1: ["1215855", "1"]
Unit 2: ["1215855", "2"]
Unit 3: ["1215855", "3"]
```

This demonstrates the real parent/child relationship without concatenating
keys or converting native identifiers to integers.

## Execution and rollback evidence

The prepared pair was loaded through B08 as restricted `arsia_loader` on
PostgreSQL 16.15, UTF-8 and UTC. All 263,151 rows were inserted in one
caller-owned transaction. Query-only temporary tables and indexes were used to
materialise the selected JSON fields efficiently; they were not schema
migrations.

After every query completed, the caller rolled back. Before and after counts
for `official_nsw` were identical: zero source rows, zero resource rows and
zero Raw rows. The run therefore supplies actual PostgreSQL results without
creating a persistent official-data load.

## Interpretation boundary

This evidence supports the selected files' real keys, parent/child
relationship, native counts, orphan check, declared-unit reconciliation and
occurrence-year scope. It does **not** claim a C semantic review, an official
publisher release version, a confirmed coordinate reference system, map
eligibility, a completed build or publication. Hash agreement and joinability
alone do not establish those conclusions.
