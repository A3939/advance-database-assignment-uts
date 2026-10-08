# Dashboard trust and usability implementation plan

Baseline: `362e8ebde2c6084fa7095afc553098e7eb6b91b6` on `peixian/arsia-platform`, clean at start.
Implementation branch: `peixian/arsia-dashboard-trust`, isolated sibling worktree `ARSIA-dashboard-trust`.
No push, merge, deployment, business-data writes, source-data changes or new business pages.

## Evidence and scope

The September 30 read-only review reproduced: NSW March 2024 (1,601 crashes) labelled simply 2024 although the full year has 18,939; Lives lost trend next to crash YoY +1.2% although deaths fell 3.8%; Compare periods opens values only; old Overview numbers briefly appear under a new LGA; heatmap calls unselected months no observation; refresh loses analysis filters. Code risks include no abort/retry, coverage checking boundaries instead of interior missing months, independent severity share denominators. Preserve existing colour, component language, map and overall layout.

## Implementation groups

1. Shared period metadata, year subtotals, metric-specific matching-month comparisons, abortable data requests, keyed Overview loading/error/retry. Validate NSW full year and March, four metric YoY, missing/zero baselines, racing/delayed/failed requests.
2. Validated URL state for source, whole-month dates, LGA, metric, interval, fixed batch/version. Restore refresh/new tab/back/forward, reject invalid or unsupported identities visibly, preserve context in navigation. Heatmap four states, single-month detail and roving keyboard focus.
3. Accurate comparison entrance, numeric relative map legend, source-specific severity spacing, explicit full-period severity recovery, Data/Evidence coverage/unit/denominator/QA limitations. Lightweight indexing only; no architecture rewrite.
4. Regression tests, production build, browser desktop/390px dark/light, month/year/cross-year/state/LGA, URL history, rapid filters, injected delays/503/retry, actual exported JSON. Save results and remaining blockers against final code.

## Acceptance matrix

| Area | Acceptance |
|---|---|
| Time | Every KPI/evidence/export retains whole-month range; yearly points expose selected/observed months and partial subtotal. Full NSW 2024=18,939; March=1,601. |
| Metrics | Trend and YoY use same metric/unit. NSW 2024 crashes≈+1.2%, deaths≈−3.8%; all selected months required, zero/unknown/missing baseline gives reason, never fabricated zero. |
| Identity | No old response appears under new filters. Abort obsolete requests. Failed scope retries unchanged, no infinite map loading. |
| URL | Source/date/LGA/metric/interval/batch/version roundtrip; invalid parameters block analysis with explicit reset. Back/forward and cross-page navigation retain scope. |
| Heatmap | Outside selection, no coverage, unknown and recorded zero remain distinct; one tab stop with arrow navigation; single month uses compact four-count detail. |
| Evidence | Source severity and crash coverage not harmonised; events vs people and fatal-share denominator explicit; unmatched records retained; regional name mapping not crash coordinates. |
| Delivery | Existing 80 unit tests + meaningful regressions, lint/typecheck/build and available actual browser checks. Clearly document anything blocked. |

## Reversible delivery

Commit this plan first, then grouped local implementation commits, then verification notes. Original checkout remains unchanged. Inspect with `git diff 362e8eb..peixian/arsia-dashboard-trust` or open the worktree; return to the original checkout for the baseline without resetting anything. If changes are later merged, use `git revert` of the implementation commits in reverse order rather than destructive reset. Keep baseline and commit SHAs in completion evidence.

## Later page route (not implemented)

Strengthen Overview (scale/people) and Analytics (time/change) first. Area Insights is a candidate for same-state multi-LGA recorded-count comparisons with unmatched totals and reference-boundary caveats; no risk/hotspot claims. Data & Evidence evolves the existing Data page. Saved Analyses can start with URL/JSON before account persistence. Pipeline operations require real Lab interfaces and permissions; current import preview is not a real pipeline. Course ≥3 reports/dashboards means three documented business use cases and DW queries, not three new navigation pages. Map these to the actual source→DW→SQL→report demonstration and synthetic-data requirement.
