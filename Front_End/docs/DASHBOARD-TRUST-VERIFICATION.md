# Dashboard trust delivery and verification

Baseline: `362e8ebde2c6084fa7095afc553098e7eb6b91b6` (`peixian/arsia-platform`).
Branch: `peixian/arsia-dashboard-trust`.
Worktree: `/Users/zhengpeixian/ZPX/UTS/Advanced Database/Assignment 2/Workspace/ARSIA-dashboard-trust`.
Original checkout remains at its baseline, with a clean tracked worktree. `pwd -P` confirms neither path resolves to a Projects/DB_Workspace path; the worktree shares only the original ARSIA Git common directory.

## Local commits

- `a139d1d97c494f88985c752f1a14dd577697a36f`: detailed scope, evidence, acceptance matrix and rollback plan, saved before implementation.
- `980871d57cb5f4d80ddee6cc6afc0ff21a744bb6`: month/year scope, validated URL contract, metric-specific matching-month comparisons, abortable read service and missing-interior-month regression.
- `98312405be398fc9c9c7b2cc5d168e443854f0b8`: URL restoration/navigation, keyed/cancellable Overview, retry, compact month detail, heatmap four states/roving focus, source-specific severity, numeric map legend, evidence matrix and browser regressions.
- `59cf000123f8d9258f7264c788d6711684854f83`: no invented numeric scale for an empty map; visible selected severity source.
- `142794d87f7b97c43b1f07d90a660a29b1d59a45`: initial delivery notes; the initial production artifact's source/test revision was `59cf000123f8d9258f7264c788d6711684854f83`.
- `f36df0fe73b0089ab7bd748991bec739795a4752`: independent review follow-up: visible heatmap states, shared date validation and exact integer map bins. This is the current production artifact's source/test revision.

## Implemented acceptance

Overview March 2024 labels Mar 2024 and yearly `2024 · Mar subtotal (1/1 months)`, with selected/observed months in JSON. The same scope appears in KPI evidence and exports. Full NSW 2024 is 18,939; March is 1,601. Analytics uses the chosen metric for both trend and matching-month YoY: crashes +1.2%, deaths −3.8%, fatal crashes −1.7%, casualties approximately −0.4%. Missing, unknown and zero baselines withhold the percentage with a reason.

Overview hides all old counts/evidence on a new scope, aborts obsolete requests, checks response source/version/batch, and retries the exact failed selection. The map instance stays mounted but hidden/inert until the matching response arrives, retaining viewport/animation resources without presenting old values under new filters. No coverage stays distinct from zero.

URLs persist source/from/to/regionId/metric/interval/overviewInterval/datasetVersion/batchId. Invalid/duplicate/unknown parameters and unsupported identities explicitly block results and offer an intentional reset. Navigation, refresh, new tabs and back/forward preserve scope. Table pagination, sort and inspected heatmap cell are intentionally transient; severity Count/Share is exported but is not part of the URL view contract.

Heatmap labels distinguish outside selection, no coverage, unknown and zero. One tab stop plus arrow navigation replaces sixty sequential tab stops. Single-month analysis uses compact four-count details rather than empty full-year patterns. Compare in Analytics transfers context to the existing YoY analysis. Severity uses source tabs and native definitions; unsupported state classifications have an explicit full-period action that changes the global selection.

Data & Evidence documents event/person units, different crash coverage and severity categories, unmatched records, denominator limits, batch/QA and regional name-to-reference-boundary restrictions. Monthly classifications are not inferred from the full-period state export. Map scales show counts and relative-selection basis; zero/no coverage remain separate and empty maps have no invented maximum. Regional map aggregation now groups records once. No source snapshot or business record was altered.

## Initial delivery verification

- `node --import tsx --test tests/*.test.ts`: 86/86 passed (80 existing + 6 targeted contract regressions); includes old demo/mock tests, not 86 real-data E2E tests.
- `npm run typecheck`: passed on implementation HEAD.
- `npm run lint`: passed on implementation HEAD.
- `ARSIA_NEXT_DIST_DIR=.next-analysis npm run build -- --webpack`: final production build passed.
- `ARSIA_TEST_URL=http://127.0.0.1:3105 ARSIA_BROWSER_CHANNEL=chrome node_modules/.bin/playwright test`: final production release 34/34 passed in 32.9 seconds.

Browser coverage includes actual JSON downloads and parsed contents for both pages, delayed requests/rapid source changes, injected 503 and exact-scope retry, four heatmap states including fixtures for null/zero, URL refresh/new tabs/back/forward and invalid batch, cross-year/month/full-period, LGA, four metrics, source-specific classification recovery, keyboard, 390px/dark/light, WebGL fallback, preserved map canvas, and desktop geometry at 1280×720/1440×900/1920×1080/2560×1440. Existing agent tests use transport fixtures without paid model calls.

Environment adjustments: shared local dependencies are linked inside an ignored node_modules directory. Turbopack rejects external worktree dependency symlinks, so the official `--webpack` option was used. A pre-existing CSS module global selector was scoped under `.page` to support webpack. The installed Playwright browser revision was missing; existing Google Chrome was used through `ARSIA_BROWSER_CHANNEL=chrome`, without downloading. Direct foreground preview sessions were not retained after an executor reconnection, so the final preview is a detached local process. Earlier dev HMR/build overlap caused one transient JSON parse failure; the same LGA scenario passed independently and the stable production suite passed.

Not claimed: real OpenAI/provider availability, Docker/Python execution, formal VoiceOver/WCAG/200% zoom certification, production performance benchmarking, raw ETL rerun, full course Lab acceptance or independent review. Area Insights, Saved Analyses and real Pipeline remain planned only in DASHBOARD-TRUST-PLAN.md.

## Preview, evidence and rollback

Preview: `http://127.0.0.1:3105/` and `/analytics`, serving this worktree's production build; HTTP verified after restart. The current follow-up artifact uses ignored `.next-regions`; the initial artifact used `.next-analysis`. Runtime files are not committed. Screenshots and actual JSON exports are in ignored `output/playwright/`; command logs are in `/tmp/arsia-trust-*.log` and `/tmp/arsia-review-followup-*.log`.

View safely with `git diff 362e8ebde2c6084fa7095afc553098e7eb6b91b6..peixian/arsia-dashboard-trust` or open this worktree. The baseline remains directly available in the original ARSIA directory; returning there requires no reset. Nothing was pushed, merged or deployed. If this branch is later merged and must be undone, revert implementation commits in reverse order (`59cf000`, `9831240`, `980871d`) on the integrating branch; do not hard-reset or delete user files. Review the branch before deciding whether to integrate it.

## Independent review follow-up

The review's two P2 findings and one P3 finding still existed in `142794d`; they were reproduced against code and addressed in `f36df0f`.

- Heatmap states now have visible labels and styling: Out with a dashed border for outside selection, N/C with diagonal stripes for no coverage, ? with a dotted border for unknown, and a numeric 0 for recorded zero. Unsupported metrics use N/S. A persistent visible key explains these labels. Existing palette, roving keyboard focus and source data semantics are preserved; unknown is not converted to zero.
- Both month forms and URL parsing use the shared `src/services/date-range.ts` contract: Jan 2019 through Dec 2026, valid calendar months, ordered dates and complete calendar months. Invalid drafts disable Apply and show a reason. A typed 2018 start or 2027 end cannot generate an invalid URL/request. February 2020 round-trips through its leap-year end date.
- `src/lib/map-scale.ts` shares the map's actual color-band formula with the legend. Integer ranges use floor-based nonoverlapping bounds; empty bins are omitted for small maxima. A maximum of 10 displays 1–1, 2–2, 3–4, 5–5, 6–7, 8–8, 9–10. A maximum of 1 displays only band 7, 1–1. Zero and unavailable values remain separate.

Verification of the follow-up production code:

- Unit suite: **88/88 passed**, including shared date/URL contract cases and exhaustive bin membership/boundary checks for representative maxima from 0 to 92,082.
- Typecheck and lint: **passed**.
- `ARSIA_NEXT_DIST_DIR=.next-regions npm run build -- --webpack`: **passed**.
- Full Google Chrome Playwright suite against production localhost: **38/38 passed** in 34.9 seconds. Four new browser regressions cover both actual month inputs, invalid Apply suppression and reload, 390px visible cell labels/computed textures and legend, and actual numeric map legend bounds including maximum 1. Existing browser expectations were updated to assert the visible N/C, Out and ? labels.
- The browser suite retains the earlier delay/failure recovery, downloads/content checks, URL/history, metrics, themes, keyboard and responsive coverage; these counts are the new run, not a claim that the previous 86/34 tests already covered the review gaps.

Evidence: `tests/review-followup.test.ts`, `tests/browser/review-followup.spec.ts`, screenshot `output/playwright/review-followup-heatmap-states-mobile.png`, and `/tmp/arsia-review-followup-head-unit.log`, `/tmp/arsia-review-followup-build.log`, `/tmp/arsia-review-followup-browser.log`. Fixtures alter intercepted browser responses only, never source snapshots or business data.

The preview was replaced with the follow-up production build and retained on port 3105 (detached process 63440 at verification time; log `/tmp/arsia-review-followup-preview.log`). The generated next-env.d.ts was restored to its tracked content after build. No original checkout files were changed. Revert `f36df0f` on the improvement branch to undo only these three follow-up fixes; the original baseline directory remains available without any reset. A later documentation-only commit records these results without changing the tested production code. Independent re-review remains the parent's next step.

Conversation organization is separate from the filesystem. Available tools expose no ChatGPT conversation-to-Project move operation; the conversation and directories were left unchanged. No Pages/Spaces substitute or guessed directory migration was attempted.
