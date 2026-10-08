# Local autonomous backend

> **1 October 2026 update:** New sessions now use a versioned model/budget profile, durable full diagnostics and progress-aware limits. The historical defaults below describe `baseline-v1`; the activated `expanded-v1` uses Sol/high and 120/200/40 call/tool/correction limits. See [AGENT_FOUNDATIONS.md](AGENT_FOUNDATIONS.md) for exact settings and Codex preparation boundaries.

This extends the existing laboratory in place. It does not reset its database, rewrite original snapshots, publish to GitHub, or establish a production deployment. Existing deterministic NSW/VIC/QLD adapters remain the first route. Complete native hash drift uses a host-owned snapshot-only revision context; incomplete/mixed native input cannot fall through to unknown-source autonomy. See NATIVE_REVISION_DESIGN.md for current limitations and pending real revision acceptance. An unknown bundle enters the autonomous Agent when deterministic recognition requests a mapping and no explicit manual profile was supplied.

The worker owns the durable job. A browser can upload, submit, cancel, inspect evidence and supply plain-text answers; closing that browser does not own or terminate the worker.

## Running and boundaries

From the pipeline directory, use the existing environment:

    .venv/bin/python -m arsia_pipeline.dev up
    .venv/bin/python -m arsia_pipeline.dev status
    .venv/bin/python -m arsia_pipeline.dev restart
    .venv/bin/python -m arsia_pipeline.dev stop

Restart replaces only this laboratory's API and worker and keeps its marked PostgreSQL container/volume. Do not restart during an active investigation unless deliberately testing recovery. Next remains on port 3100; the API uses the private Unix socket in the 0600 runtime configuration. The worker authenticates to the Next model gateway with a separate private bearer token. Next holds the provider API key. Generated adapters receive neither token nor database credentials.

The dedicated Docker adapter image must be built separately. There is no host-Python execution fallback. The old compose.local.yaml only rehearses the deterministic workflow: it does not provide its worker with a Docker executor or a trusted model gateway.

The lifecycle writer rejects ARSIA_IMPORT_CONFIG. Disposable integration tests use that override to select their uniquely named and marked database, but cannot overwrite live runtime configuration. The model gateway client never initializes or writes runtime configuration. Token initialization belongs to the lifecycle manager.

## Durable investigation

Agent sessions store the complete checkpoint: contract, adapter code, full model transcript, pending calls, admitted files/documents, repeated diagnostics and cumulative budgets. Agent steps record model/tool starts and results against the worker attempt. Model calls and code/contract corrections have counters separate from crash-recovery attempts.

Defaults are 80 model calls, 120 tool calls, 24 corrections, 3,600 cumulative active seconds and 2,400 cumulative sandbox wall seconds. The model-call ceiling is checked only before a new model request; tools returned by the final permitted response still execute under their tool, compute, wall-time and QA gates. It never permits model request N+1. Active time survives recovery and is refreshed through cancellation hooks at least every five seconds during cooperative work; time awaiting user input is excluded. Three consecutive model transport failures pause the session; a successful response resets that consecutive counter while preserving the full failure history. Provider rate limits use a bounded 30–60 second cancellable delay, honor sanitized retry-after hints, and persist a waiting_for_model phase. Repeated identical tool failures require a different diagnostic approach and eventually pause with paired call/result evidence. Three queued automatic crash recoveries exhaust the scheduler recovery allowance. This is counted from durable worker_lost dispositions, separately from total attempt number, manual retries, cancellations, model reasoning and adapter corrections. A manual retry does not reset that accumulated recovery count.

At approximately 60 KB or 100 items, a deterministic checkpoint replaces older model context. It includes current code/contract, file and document indices, budgets, recent runs, sample gate, validated summary/QA and registered IDs, followed by up to eight complete call/output pairs. Exact citation spans and document file IDs are retained; omitted documents/code can be reread with bounded tools. Each model request also includes a deterministic next controlled action, completed tool counts and remaining cumulative budgets. The recommendation follows sample execution → independent sample QA → full execution → independent full QA → registration → requested publication; it never authorizes bypassing a gate. Recorded QA failures direct inspection/correction rather than blind repeated validation. read_adapter accepts current or an empty version to inspect saved code. Model-step evidence records the gateway model-policy and SDK-contract SHA values when supplied. The unabridged transcript remains stored. A separate bounded investigation memory reconstructs successful bundle schemas, the latest effective profile per file/table, complete-key candidate counts, relationship aggregates and exact document citations from durable tool steps. Its compact column layout retains every observed field, date format/range, type, null/duplicate count and bounded safe category frequencies. A separate exact-text fact index gives general coordinate-system identifiers, date formats and observed source-field definitions priority over repetitive long snippets; it preserves original document IDs, file IDs and character offsets without treating those facts as QA admission. Full transcript evidence remains unchanged; omissions are explicit and no raw row samples are included. On the actual cancelled SA investigation it retained all 64 fields across three profiles and its relationship results within about 24 KB. Code and contract edits invalidate QA. A resumed attempt retains code/evidence but must execute and validate fresh output. Pending tools are replayed under the single worker lock, and unfinished prior steps are marked interrupted. Independent sample QA returns sample_only and cannot register or publish. A matching code, executed contract/document hash and image must pass sample QA before full execution; full execution also prechecks official evidence. Only full trusted admitted results can register or publish.

Tools can inspect source structure and relationships, retrieve official documentation, write or patch an immutable adapter version, run it in Docker, inspect diagnostics, invoke independent QA, register the version and request publication. A publish_candidate tool result means ready for the trusted PostgreSQL transaction; it is not a claim that publication committed.

## Additive schema and publication

Numbered, hash-checked migrations run transactionally under a migration lock. Changed bytes for an applied migration are refused. Added tables cover source/adapter versions, Agent sessions/steps, canonical casualties and observations. Existing jobs, batches and releases remain intact. Migration 3 adds unique official dataset identities. Registration binds trusted Socrata host/dataset ID, ArcGIS layer URL, verified CKAN ID/name aliases, or a specific official resource URL to one logical source. Existing admitted versions are backfilled under the registration lock before any new binding; a conflicting alias returns the existing source ID instead of publishing a duplicate.

The v2 loader verifies full admission, registered adapter bytes and the exact executed source contract including host-registered documents. Artifact hashes are checked before loading and while streaming COPY. Crashes, units, casualties and aggregate observations are physically stored in separate canonical tables. Observations never become synthetic crash rows.

V2 storage uses canonical_id as physical identity so two resource roles with the same raw key cannot collapse. Payloads retain the original complete record_id, role and lineage. Database reconciliation compares independent candidate totals and checks source identity, unique canonical IDs and role-specific foreign keys.

Every published batch is a complete readable source version. A snapshot can replace its source only without silently narrowing published history. A partition replaces an evidenced complete-month interval and preserves outside rows and associated children. An incremental update upserts complete stable keys and retains absent keys. Composed aggregates are recomputed from the database. Coverage intervals preserve gaps; an incremental-only first version cannot prove empty intervals are complete.

COPY, reconciliation, cancellation arbitration, the source-to-batch release mapping and terminal job status share a transaction on the same session that holds the global heavy-worker lock. Losing that session aborts its candidate. Cancellation checks stop immediately if the lock connection is closed or reports UNKNOWN, so an old worker cannot continue generating work after losing that authority. Cancellation and final publication serialize on the job row. A lost commit acknowledgement is resolved by reading committed job state.

Repeated v2 input retains the current release, including later updates; it never rolls a source back to an older batch. Historical releases keep their original mapping.

## Website API

GET /catalog?release_id=<optional UUID> selects the latest or a specified immutable release. Each source includes its stable ID, batch/job/version IDs, jurisdiction, publisher, coverage, definitions, summary, limitations and capabilities. Monthly capability comes from actual stored date precision, including native batches.

GET /query requires release_id, source_id, from and to. Dates select complete calendar months. The result contains source coverage, requested interval, completeness, availability, nullable metrics, actual yearly/monthly rows, severity, units, QA and supported geography.

An empty fully covered interval becomes zero only for metrics that source measures. Missing metrics stay null. Annual records cannot answer a partial-year filter. Monthly series do not invent absent months. Multiple observations are summed only when an evidenced contract explicitly declares additive semantics; otherwise individual aggregate values and dimensions remain available.

Validated geography exposes bounded source regions and rounded 0.1-degree cells, not an invented ABS boundary crosswalk. A map requiring LGA boundaries can still report that capability unsupported.

Submit/retry accept optional answers text and an optional advanced manual profile. The default empty body enables autonomy. Job polling includes a small Agent phase, actual execution/QA counters and five fixed-language progress summaries; it never sends adapter code or full model results. Explicit job evidence includes Agent session/step results without private host paths or credentials.

## Verification

The PostgreSQL suite uses explicitly synthetic admissions to test the trusted loader boundary; it does not claim that a live model produced those adapters. Every module creates a separate arsia_imports_test database and checks its marker before cleanup. It never truncates the running laboratory.

    .venv/bin/python -m pytest tests/test_backend.py tests/test_autonomous_backend.py -q --tb=short

Tests cover legacy COPY, four v2 grains, role identity, artifact tampering, sample rejection, contract binding, rollback, cancellation, partition/incremental history, no-change replay, immutable queries, null/zero semantics, annual observations, transport failures, correction persistence, interrupted pending-tool recovery, independent sample QA, context compaction and configuration isolation.

Executor isolation, source retrieval, canonical projection and independent full QA have separate tests. Real model and official full-source acceptance are recorded by the integration run and are not inferred from this suite. A redacted audit of the fixed runtime/test configuration incident is under artifacts/imports-local/audits/runtime-test-isolation-recovery.json.

The coordinated pre-restart Python run on 2026-10-01 passed 225 tests (recorded in artifacts/autonomous-imports/python-tests-current.log). The subsequent ACT model retry is a separate live acceptance run; this test count does not imply that it has published successfully. During that run the active service modules remain frozen. The update_compatibility guard is now called inside the publication transaction before COPY. Fourteen pure tests and six PostgreSQL rejection cases verify that partition/incremental updates cannot change resource roles, grains, complete-key definitions or relationships while retaining old history; rejected candidates leave the release unchanged. A complete evidenced snapshot can explicitly rekey. The latest focused Agent/publication run passed 70 tests; subsequent live-model acceptance is recorded separately.

## Scoped container recovery

Before launching an Agent sandbox, the executor writes an immutable 0600 host receipt with the instance, job, attempt and run identities, exact mount directories and owning worker PID. Corresponding Docker labels bind the receipt hash. The receipt is not mounted into generated code. After acquiring the global database session lock and before recovering/claiming jobs, a new worker validates receipt, exact labels, database attempt and mounts, then removes only an incomplete owned container by its full immutable ID. Foreign marked databases and projects are ignored; ambiguous local ownership blocks new heavy work without deleting an unknown container. Per-run and startup audits preserve the evidence.

Twenty-two offline ownership tests plus a real container in a separate marked test database verified scoped removal, unchanged release and retained input evidence. This is separate from actual SIGKILL recovery acceptance, whose plan and opt-in watcher are documented in AGENT_LIFECYCLE_ACCEPTANCE.md. Cleanup runs at worker startup, so deployments still need a service manager to restart a dead worker; it is not an independent sandbox timeout watchdog.

The latest focused run after the model-budget edge, separate crash-recovery allowance and generic official-text memory fixes passed 108 tests in 14.95 seconds. The actual SA checkpoint review retained all three profiles and the previously omitted official coordinate-system text within the 25 KB memory budget. This is evidence-retention verification, not a claim that the model has already corrected and published geography.

## Documented capability and reconciliation review

Admission policy canonical-v2-auto-admission-3 adds two narrow deterministic reviews after official receipt/hash and dataset-connectivity checks. Both helper hashes are part of the trusted implementation fingerprint. Geography review compares actual selected table headers with connected official field/CRS declarations. Omitting a proven coordinate pair returns actionable exact evidence; absent or ambiguous official CRS evidence still permits unsupported geography. The review does not invent a CRS, alter a contract or accept a model-written opt-out.

When a crash casualty total and a related casualty resource both exist, reconciliation applicability cannot remain implicit. Prefer crash mapping.declared_casualties for the source-declared applicable total. Otherwise definitions.casualty_table_complete=true and evidence.casualty_scope must contain exact dedicated connected official excerpts with resource_role, document_id and quote. The same sentence must bind the complete child key and explicitly identify a complete casualty register/table/dataset. Partial/false scope currently requires clarification; a word such as "only" in a fatality definition cannot authorize it. Full equality runs only for the parent/child pair in verified scope decisions. Matching row counts are not evidence of completeness.

Broad catalogue search results can establish source discovery but do not supply these stronger per-resource scope/CRS declarations; fetch dedicated package or layer metadata. Grounding and omission review share coordinate evidence logic. ArcGIS geometry WKIDs apply only to trusted geometry reader fields, not ordinary X/Y attributes. Diagnostics preserve ArcGIS WKID authority and code; recognized CRS equivalence is checked through pyproj's authority database without inventing an EPSG prefix.

Sample QA with registered official documents and full QA run these checks; full-run preflight uses the same trusted inputs. The focused geography, casualty scope, grounding, canonical and Agent suites passed 116 tests in 7.71 seconds. A read-only check of the first SA publication correctly found both omitted geography and undeclared casualty reconciliation. An in-memory counterfactual with evidence-backed mappings passed the proof checks; no stored contract, source version or release was modified. A new real-model import remains necessary to verify autonomous correction and publication.

## Generalization policy 6 (2026-10-02)

Later isolated development adds structured immutable-document references and
offline `TransformPlan` receipts. Each geographic execution first probes only
the immutable image, with no adapter/input mounts or network. The host derives
the same operation independently and records both dependency receipts; matching
pyproj version numbers alone do not prove matching PROJ database bytes. Frozen
operations, grid hashes, axes, areas and accuracy estimates enter admission;
canonical rows include the operation hash and still compare exactly. Missing
preferred grids, ballpark/epoch/unsupported dimensional plans and runtime
disagreement block explicitly. Database accuracy is an operation estimate, never
a guarantee of the original crash coordinates' positional accuracy.

New isolated ACT/SA acceptance, 109 database boundary regressions and 11 actual
container tests passed. The new SA publication was also checked against the
existing independent v3 full-data oracle: 1,165 assertions passed, including
63,230 map points and 9 unknown points. Counts/keys/facts remain exact; only the
independent source-coordinate oracle retains its documented 1e-7 degree limit
(observed maximum approximately 5e-9 degrees). This is not an administrative
boundary or survey-accuracy certification. Reports and the new owned read-only
verification tool preserve old evidence and do not update the live release.

The operation controls follow the installed
[pyproj Transformer API](https://pyproj4.github.io/pyproj/stable/api/transformer.html)
and [database metadata API](https://pyproj4.github.io/pyproj/stable/api/database.html).
The fixed offline illustrative-map policy is an ARSIA implementation choice;
survey-grade requirements and more complex transforms remain unsupported.


## Codex compact evidence path (2026-10-02)

The legacy byte-based context memory above is distinct from the active Codex
bridge. Codex now receives bounded routine result projections with exact full
result-file hashes and JSON Pointer retrieval through the existing read_task_state
tool. Host-written facts/index/issues snapshots rebuild from durable history.
Omissions are explicit; no source quote is silently truncated into evidence.
Read CODEX_RUNTIME.md for limits and hash scopes. This changes context delivery,
not sample/full admission, publication authority, budgets or model routing.
New Codex sessions also pin scoped issue progress. A stalled investigation is
stopped before its next model request, with durable diagnostics retained; old
sessions retain their legacy rule. The UI shows unresolved checks, actions since
verified progress and the last progress time. Deterministic bridge/DB and mocked
browser regressions passed. Later ACT cold-start and isolated browser experiments
are recorded in `artifacts/generalization-implementation-20261002/`; they do not
establish a comparative provider-token saving or cover every source.

## Lookup host replay (development policy 17)

Physical table inventory includes explicit lookup parents separately from fact
grains. QA rebuilds complete parent indexes even for child sample runs, compares
all emitted fields and lookup lineage, and verifies child conservation. Diagnostic
success still ends at `LOOKUP_ADMISSION_NOT_INTEGRATED`; source field semantics
and real-source lookup publication have not passed admission. Cache/registry
serialization binds parent files/partitions and excludes ephemeral upload IDs.
Tests with mocked registry authority verify only serialization and rebinding,
not real semantic approval. See AUTONOMOUS_CONTRACT.md for the exact boundary.

Policy 18 adds physical-origin field/CRS/category diagnostics and a scoped CSVW
relation verifier. It reuses the existing evidence graph, applicability and
immutable reference checks; it does not introduce another catalogue or trust
store. Child evidence cannot certify parent fields. The remaining system-owned
lookup admission blocker carries these diagnostics while count populations,
omitted supported capabilities and actual source acceptance remain unfinished.
