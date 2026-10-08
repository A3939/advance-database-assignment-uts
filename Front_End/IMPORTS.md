# Imports · local autonomous workflow

`/imports` uploads real bytes to the dedicated local import namespace. The default
submission uses the Python worker's autonomous Agent. Users upload one source's
related data tables and optional source documentation; no JSON profile or script
selection is required. Job progress and decisions come from persisted worker
state. A necessary unresolved question can be answered in plain text, or the user
can add a missing file, then resume. Closing the page does not stop a submitted job.
The selected job displays the worker's current investigation, sample, full-data
and quality-check phase, recorded execution counts, automatic revisions and recent
actions. These values come from the bounded `job.agent` status payload; they are
not elapsed-time estimates or inferred completion percentages. Source evidence,
quality results, readable code versions and the full record load only when opened.
An actual model-service rate limit shows a saved waiting state while the worker
performs its cancellable retry; the page does not simulate investigation progress.

Successful publications join the same Overview, Analytics, Data, Ask AI and Studio
through `local-integrated-v1`. Original `data/` files and snapshot bytes are not
modified. These are local development publications, not a production deployment
or an automatic claim of historical course-pipeline acceptance. See
[pipeline/README.md](pipeline/README.md) and [pipeline/CONTRACT.md](pipeline/CONTRACT.md).

The advanced reviewed `generic-v1` profile and schema-only advisor remain available
for explicit compatibility/testing. A schema advisor draft remains unconfirmed;
it cannot authorize publication. This option is not required by the normal Agent
workflow. Source evidence, full QA, file receipts and execution logs are under
details. Counts from different datasets are never pooled into a national total.

## Website releases

`/api/data/catalog` resolves a local composite catalog: immutable baseline references
plus source-specific local publications. An exact `official_nsw`, `official_vic` or
`official_qld` publication replaces that baseline source in the composite catalog;
other source IDs remain independent even when they share a jurisdiction.

A fresh session resolves the latest local release and records its UUID in the URL.
Every chart, API call, export and Agent/Studio run uses that fixed `releaseId`.
Source batch IDs are recorded separately in metadata. The default session discovers
new publications; an explicitly restored URL remains pinned. The header's local
data button intentionally opens the latest catalog. Existing `official-v1` URLs
continue to use the original verified snapshots. Missing historical local releases
fail closed instead of substituting current data.
An active local session also retains its selected release if discovery temporarily
cannot reach the import service; it does not switch back to the snapshot silently.

Catalog-driven sources and coverage populate the existing controls. Monthly and
annual counts come from exact-release database queries. Missing measures remain
null, and unsupported geographic aggregates remain unavailable. The immutable
baseline LGA extension is used only for baseline references, never silently joined
to a different imported batch. Import result links open Overview with the exact
source, coverage and publication release.
Annual-only observations remain annual in Analytics and the Studio workspace;
the provider does not divide them into invented months. Comparisons require both
periods to be fully covered by the selected source, rather than the wider catalog.
If declared coverage starts or ends within a month, the query selects the enclosing
calendar months while evidence retains the exact source dates. That wider query
remains partially covered; its comparison is not presented as a full period.
The same coverage rule applies to AI trend changes and monthly contributions.
Known partial counts remain visible, while unsupported comparisons stay null.
Charts with no known values explain the missing metric; they do not draw zero
observations. Annual-only sources can still show a known annual measure when
crash counts or monthly data are unavailable.

Sources with an admitted coordinate transformation can expose rounded 0.1-degree
crash-count cells. This is an independent map layer with a local WebGL renderer,
SVG fallback and accessible values table; cell centres do not identify exact crash
sites, ABS areas or city boundaries. The map keeps one source selected, and does
not enable area searches or region filters. Counts for other metrics are unsupported.
Returned/total cells, truncation and located/unlocated crash counts remain visible.
If complete coverage metadata is absent, the interface says that completeness is
unknown. A source without a trusted geographic capability remains unsupported.

Ask AI and Studio use the same fixed-release `geographic_cells` workspace table,
with source identity and truncation retained. The original LGA tables remain a
separate capability. Provider and WebGL/SVG browser tests use an explicitly
synthetic fixture; actual coordinate acceptance requires a separately verified
source publication.

## Transport and isolation

- `src/components/imports.tsx` and its CSS module replace the old metadata-only import workflow.
- `src/services/imports-client.ts` sends `File` bodies by binary PUT, displaying
  actual browser upload progress. Worker progress is read from durable job events.
- `src/server/imports/bridge.ts` accepts only declared methods, UUID job paths and
  query keys. It streams to the private Unix socket with backpressure; it does
  not buffer an uploaded file in memory.
- Every request must use an allowed loopback Host on port 3100. Mutations require
  an exact matching Origin. Browser GETs may use same-origin fetch metadata plus
  an exact Referer origin when Origin is absent. This is a local-only guard, not
  production account authentication.
- The bridge reads the fixed private `artifacts/imports-local/runtime.json` only
  to resolve its socket; configuration and database credentials never reach the
  browser. Socket paths are constrained to the private local import namespace.
- Limits: 512 MiB per binary file, 1 GiB and 12 files per bundle, 256 KiB per
  ordinary JSON request, 250 KiB of editable profile text, and 8 MiB per API
  response. The backend additionally enforces pending-upload and disk reserves.
- Browser aborts close the upstream request. The backend removes incomplete
  uploads. If a receipt is lost, inspect admitted files before reuploading.
- Only metadata/QA/aggregate JSON is exposed. Failed upstream responses are
  replaced with bounded messages instead of forwarding raw errors or paths.

Use the existing 3100 Next.js service. The private API/worker lifecycle is owned
by the laboratory launcher; do not restart it while integration work is running.
No extra website preview port is required.

## Verification history

The current full-volume acceptance, discrepancy assessment, real model fixture,
recovery injection and protected-data checks are recorded in
[pipeline/ACCEPTANCE.md](pipeline/ACCEPTANCE.md). The seven original files were
also uploaded through the real 3100 bridge, including the 213 MB QLD input.
The optional advisor rejects malformed mapping/category shapes and attempts at
most one structural repair; every returned draft remains unconfirmed.

Safe direct checks (historical browser suites are not an isolation boundary):

```sh
npx tsx --test tests/imports.test.ts
```

The historical Imports/Studio writing suites are excluded by the default Playwright configuration. Do not invoke a replacement configuration without a verified dedicated runtime/DB/Studio binding. The following paragraphs describe historical runs, not permission to repeat them against the current service.

Eight historical transport/input tests covered loopback restrictions, path/parameter rejection,
real Unix-socket binary hash fidelity, unknown-length size limits, cancellation,
bounded output and error sanitization. Three real browser workflows verify missing
resources followed by publication, reload/evidence, failure retaining an older
publication, and explicit cancellation/retry. They use a `browser_fixture` source
with synthetic records, distinct from native data. A separate browser test mocks
only the assistance workflow and verifies that an AI draft needs explicit review;
it makes no paid model call. The existing navigation test selects and removes a
file without submitting any job.

TypeScript, targeted ESLint and these checks passed during development on the
existing local preview. Desktop and 390px dark/light screenshots are under
`output/playwright/imports-*.png`. Historical test success is not a production,
multi-user, Linux resource or VPS deployment guarantee. Native full-data
verification and resource evidence are documented separately by the integration
verifier; the UI tests above do not substitute for it.

## Integration regression checks

```sh
npx tsx --test tests/catalog-release.test.ts
ARSIA_BROWSER_CHANNEL=chrome npx playwright test tests/browser/catalog-release.spec.ts --output=output/playwright/website-tests
npm run typecheck
```

The catalog unit tests verify native-source deduplication, separate same-jurisdiction
datasets, dynamic source/date validation, historical release refusal, and matching
website/analysis-tool/Studio-workspace counts with unknown measures preserved. The
new browser test uses an explicitly synthetic ACT UI transport fixture: it verifies
Overview → Analytics → Ask AI context and release consistency, not real ACT import
adaptation. Real-source and live-model acceptance are recorded separately in the
pipeline acceptance report.

The opt-in `scripts/verify-local-release-analysis.mjs --source <catalog ID>` first
checks actual 3100 provider responses. Adding `--live` calls the configured model
through Ask AI and Studio, checks all four metrics against the same release, saves
a validation study and verifies its exported ZIP. Add `--oracle <JSON path>` to
compare total, annual and monthly metrics against an independent source oracle
before any model call; a mismatch stops verification. The NSW run on 1 October 2026
passed with 92,082 crashes, 1,388 fatal crashes, 1,507 deaths and 78,154 casualties;
its evidence is under `artifacts/analysis-verification/local-NSW/`.
`tests/browser/local-release-live.spec.ts` is a separate opt-in, GET-only check of
the real Overview, Analytics, Data and saved Studio screens. It uses no mocked
HTTP responses and does not submit an import. These native-source checks do not
establish unknown-source Agent acceptance.

The ACT publication `act_open_data_6jn4_m8rx` also passed a real Ask AI/Studio check
on 1 October 2026, pinned to release `6c550eaf-1ff1-46db-b1e2-0d2ef4e16499`.
Its 76,657 crashes, 105 fatal crashes, null deaths and null casualties, all 12 annual
rows and 141 monthly rows matched `independent-oracle-v2.json` exactly before the
model calls. Both answers retained the unknown measures and actual source coverage
through 7 September 2026. The saved study and ZIP evidence are under
`artifacts/analysis-verification/local-act_open_data_6jn4_m8rx/`; original-file and
row-level acceptance remain in the separate pipeline verification report.

## Current local integration work

See [the 2026-10-03 implementation and acceptance ledger](docs/INTEGRATED-OPTIMIZATION-20261003.md). Known recipe hits still run new sample/full QA. Native, reviewed manual and autonomous candidates share the final publication policy, with distinct source authority. Actual removals require applicable authority; observed date extent alone permits neither complete-period zero filling nor deletion. Missing geographic proof can yield an explicitly limited publication with raw fields and unresolved requested capabilities retained. Resource licence status remains separate from source provenance and redistribution permission.

Official-source API and website-provider acceptance uses a new managed PostgreSQL instance, cold Python runtime and a private read-only Unix socket. It does not change the normal Next.js catalog. Those service results are not browser results. Historical live scripts that save normal Studio studies or invoke models are not ordinary regression commands.
