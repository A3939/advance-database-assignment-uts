# Codex import runtime (local integration)

New sessions may select `agent_engine: "codex"` with `agent_profile: "expanded-v1"`
in the private import runtime configuration. Existing sessions pin their engine
and policy; enabling Codex never resumes, republishes or rewrites old jobs.
`legacy` remains available for controlled comparison. Do not print private configs.

## Responsibilities

`codex_runtime.py` launches the supplied Codex CLI 0.159.3. Codex owns reasoning,
context and tool selection; the old `AgentSession.run()` loop is not invoked.
`AgentSession` remains the durable business-tool implementation. Its evidence, registry and transaction publication rules are retained. Admission
policy 4 adds deterministic 8-decimal coordinate representation and field/hash
diagnostics; exact independent row reconciliation remains mandatory.

The per-attempt `codex_bridge.py` exposes authenticated stateless HTTP MCP tools
and a Responses proxy. It binds random loopback ports with fresh task-scoped
capabilities. It cannot accept arbitrary upstream URLs. Provider keys remain
in Next.js on port 3100; database credentials remain in the trusted Python worker.
Only the task's Sol/high model is accepted, with 24,000 output tokens. Every
provider request reserves a persisted model call; completed receipts contain real
provider usage. Missing receipts are unknown, not zero. Codex automatic transport
retries are disabled, so a transport error preserves a resumable task.

Simple Ask AI tasks retain GPT-5.6 Terra/high; reasoning tasks, Studio and Imports
use GPT-6.1 Sol/high. The import engine change does not alter that routing.

## Task files and isolation

Runtime state lives under `artifacts/imports-local/codex-tasks/<job>/`:

- `<attempt>/task/evidence`: host-written full SDK, source metadata, exact
  diagnostics, contract, adapter, complete tool results and registered documents.
- `<attempt>/task/proposals`: model-edited adapter and contract proposals.
- `<attempt>/task/scratch`: temporary diagnostic programs.
- `home`: durable Codex session state, without personal auth files.
- `<attempt>`: boundary/identity receipts, prompt, provider request evidence,
  JSONL events and stderr. Keep these private; they can contain source evidence.

This tree is separate from adapter inputs/outputs. Codex's own cache symlinks
cannot cause the data executor's no-symlink quota scan to reject safe raw data.
The legacy prototype attempt-home compatibility marker is restricted to a UUID
within the same job and exists only to preserve early test evidence.

An outer macOS Seatbelt boundary covers Codex and its descendants. It permits
read access to required system runtimes and this task only; write access to
proposals, scratch and its credential-free Codex home; network access to the
single task bridge only. It does not expose the repository, raw uploads, Docker
socket, database socket, website port, personal home or API keys. The inner
Codex permission setting is `danger-full-access` **inside this outer boundary**;
it is never used as an unconfined host launcher. Unsupported operating systems
fail closed. Linux server deployment needs a separate container launcher and
Linux Codex binary; the supplied macOS binary is not deployable there.

OS probes exercise denied host/project reads, volume aliases, symlink escape,
host/evidence writes and unrelated ports, plus allowed task writes and bridge
access. These checks are local isolation tests, not a claim of comprehensive
security certification or resource isolation equivalent to a Linux container.

## Persistence, interruption and publication

Engine, Codex thread ID, cumulative counters, code, contract and registered
source evidence are checkpointed in PostgreSQL. `codex exec resume <id>` reuses
that precise thread and its durable home. A new worker attempt gets a fresh
workspace and must repeat sample/full execution and independent QA.

MCP calls serialize through the owning session, consume the same tool/correction
budgets, and persist complete outputs before returning. Shell/file events also
consume the tool allowance and are recorded. File submission uses current host
version hashes; it cannot authorize publication. No-change, QA and atomic
release publication still use the existing trusted worker transaction.

Cancellation checks run during model waits and all controlled tools. The trusted
supervisor terminates its Codex process group when the worker dies or requests
termination. Task capability endpoints close on exit. Logs, databases, rollouts
and candidate versions are preserved. An intentional evidence stop or transport
failure is not reported as successful ingestion.

## Acceptance

Run unit/integration tests with `.venv/bin/pytest -q`. The regular DB fixtures
create and remove only their newly-created disposable databases. Real Codex
experiments use `tools/verify_codex_import.py --confirm-real-model`; they preserve
their own uniquely-marked test DB, private config and every job/attempt. They do
not select that DB as the website's current data source.

See `artifacts/autonomous-imports/codex-integration-20261001/` for live receipts.
The independent source oracle is never provided to Codex. An actual full-data
publication plus a separately computed acceptance report is required to claim
SA ingestion success; protocol smoke tests alone are insufficient.

Official interfaces used:
https://learn.chatgpt.com/docs/non-interactive-mode
https://learn.chatgpt.com/docs/extend/mcp
https://learn.chatgpt.com/docs/config-file/config-reference

## Cross-platform coordinate fix

The real SA test exposed a 7.1e-15-degree latitude difference between macOS and
Linux using identical projection code, pyproj 3.7.2 and PROJ 9.5.1. Canonical
coordinates now use 8 decimal places; maximum rounding displacement is under
0.001 m per axis in latitude. Raw coordinates, source CRS and all counts remain
exact. Policy `canonical-v2-auto-admission-4` still compares complete rows exactly.
The independent acceptance oracle retains its original 1e-7-degree tolerance; it
was not altered. Executor image `arsia-import-adapter:3` contains the matching
canonical code; image `:2`, failed attempts and their evidence remain available.

Codex native auto-compaction is configured at 95,000 tokens. Both streaming
Responses and the dedicated `/responses/compact` transport are task-scoped and
count against the persisted model-call budget; compact token receipts are saved
when returned. The old harness's byte-based context compactor is not used by
Codex. Full task evidence remains on disk after compaction. Provider rate limits
can still interrupt a task; they do not reset its budget or authorize admission.

## Verified local activation (2026-10-01)

The local runtime now selects `codex` for new Imports sessions. The existing
25 jobs and release `317b799e-8637-4ecb-90bd-4590dc556324` were unchanged; no
experiment database was selected by the website. The owned API and worker were
restarted while idle, and the website's Imports page, health, catalog and jobs
routes responded successfully on port 3100. Old saved sessions retain their engine.

The isolated SA job `098629b6-b3ab-45e2-bf84-2e7d0b332fe5` published 63,239
crashes, 134,981 units and 23,892 casualties. Independent read-only acceptance
passed 1,165 checks, including every row's keys/facts and source-coordinate
comparison. It used no oracle as model input. A real cancellation left no active
worker, running step or publication; resume reused the same Codex thread and
cumulative counters, then reran both sample and full QA in a fresh attempt.

This was development acceptance across four attempts, including a coordinate
representation fix, intentional cancellation and provider rate-limit interruption;
it is not evidence of an uninterrupted first-attempt run or all-state coverage.
The recorded native `compacted` event used regular Responses with this custom
provider. The dedicated compaction endpoint is supported and unit-tested but was
not exercised by the live run. The host stops the Codex process after the publish
tool authorizes the candidate; CLI exit status alone is not ingestion success.
The durable worker publication and independent acceptance establish success.

Recovery details, usage receipts and source snapshot are in
`artifacts/autonomous-imports/codex-integration-20261001/README.md`.

## Current generalization development (2026-10-02)


The actual Codex MCP bridge uses `codex-result-projection-v1`: routine returned
outputs target 6 KiB, failed/paused diagnostics 12 KiB. Explicit paginated
reads preserve exact requested content up to the existing 48 KB bridge boundary.
These are output byte limits, not token budgets or proof that provider usage
decreased. Full safe result files and durable database results remain intact.
Each response records full/returned byte counts, the full result-file hash and
a retrieval call. Long quotes are omitted explicitly, never silently shortened.

`read_task_state` accepts exact JSON Pointer selection before character pagination
and still restricts results to the owning session, excluding model steps. Its
`content_hash` identifies the complete durable value; `sha256` pins the complete
selected serialized value before pagination. Durable values include host_context,
so this differs from the bridge result-file hash when that context is absent.

Atomic `evidence/facts.json` and `evidence/index.json` are rebuilt from durable
tool history, including on resume. Facts keep a bounded latest-by-tool view
(24 KiB before pretty-printing) with explicit omissions; the index retains exact
step references and hashes. `evidence/issues.json` contains the host-derived
`progress` report and full `diagnostics` references. New Codex sessions pin
`scoped-issue-progress-v1` in their checkpoint; historical checkpoints retain
legacy accounting. No historical session is silently migrated.

Issue identity binds the diagnostic code, sample/full gate, source, resource
grain/key, field/claim, semantic conflict values and QA policy. New URLs, hashes,
quotes, edits and rereads do not renew progress. A disappearing diagnostic in an
early-return failure does not prove resolution. Positive scoped gate/check
outcomes resolve issues; an explicit matching-policy admission may clear its
prerequisite gates. Sample admission cannot clear a failed full gate. Complete
measurements count before blockage; unverified partial evidence does not count.

Three unchanged gate observations advise replanning; the existing configured
20-tool warning/40-tool stop remain unchanged for expanded-v1. Old unresolved
issues cannot be masked by unrelated passing checks. Durable history rebuilds
on resume, and the bridge checks for a stall before reserving a new model call.
The Imports status API exposes counters and the last verified progress time,
not issue subjects. A stall asks for investigation review rather than assuming
that the user must supply a missing document.
No view grants admission. Offline bridge tests cover compaction, exact retrieval,
task boundaries, budget accounting and resume. Real-model token benefits remain
unverified.

The runtime instructions and SDK now teach hash-pinned JSON Pointer, XML
expanded-name and PDF page/text references through `read_document(locator=...)`.
The same references reach the existing TaskBridge; this adds no second harness.
Raw/cached record data remains withheld. References are re-resolved and checked
for source/field applicability by trusted QA, not accepted on model confidence.

Policy `canonical-v2-auto-admission-16` requires an offline coordinate operation
receipt from a separate immutable-image probe for geographic candidates. Missing
executor support, preferred grids or host/executor operation disagreement produces
a system-owned blocker with no request for another source dictionary. Generated
adapter output cannot supply this receipt. A new image is required; do not resume
old attempts or silently relabel their previous admissions.

Current development also filters supported resource/temporal evidence scopes
before field, CRS and capability review. Known applicable CRS contradictions
cannot be hidden by omitting a citation. Retained-history publication rejects
unproven semantic changes before COPY; full snapshots remain subject to their
existing coverage and admission checks. See AUTONOMOUS_CONTRACT.md for the exact
supported scope subset and the limits of automatic semantic equivalence.

The development image `arsia-import-adapter:generalization-20261002-r4` was used
only by explicit isolated acceptance commands. The running API/worker configuration
and default historical image were not switched in this batch. ACT/SA deterministic
acceptance and the SA independent read-only oracle passed; no new real-model or
browser-upload acceptance is claimed. Current details and remaining P0 work are
in `artifacts/generalization-implementation-20261002/PROGRESS.md`.

The host QA now checks scoped ArcGIS category dictionaries: coded-value domains
and single-field unique-value renderers, including groups taking precedence over
legacy infos. Exact category citations are required. Default symbols cannot
authorize new codes, different native labels cannot share one canonical category
identifier, and unfamiliar outcome labels remain unknown. This bounded source
classification check does not establish common mortality windows or comparable
injury categories between publishers. Unsupported expressions/composite renderers
need a reviewed system capability; repeated source searches cannot fix them.
Existing text-only category grounding is explicitly labelled as legacy scope,
not upgraded to structured semantic proof. The policy 9/10 changes are host-only;
the r4 data-executor SDK remains unchanged.

Policy 10 also binds source-completeness and public-export code dependencies.
Publication checks actual omitted identities for all update modes, after retained
history is composed and before committing the release. Removal requires current
host-derived complete-resource evidence. The bounded positive path verifies an
authorized ArcGIS v2 whole-layer export against its inventories, count, page
hashes and reconstructed input bytes. It does not establish historical coverage
or unchanged field values during retrieval. Its observation must postdate the
source version being replaced to authorize removal; an older complete export
does not gain deletion authority through a new adapter version. Other resource formats currently
need a reviewed completeness verifier when an update would remove records.

Casualty completeness uses whole affirmative, exact-key declarations from scoped metadata or text. Negated/conditional examples and uncited conflicting partial declarations cannot authorize equality. Hash-pinned references are checked without quote fallback. `CASUALTY_PARTIAL_SCOPE_UNSUPPORTED` indicates a reviewed partial-table reconciliation implementation is needed; it does not ask the user to supply the same dictionary again. This bounded grammar does not establish every partial population or direct count meaning.

Direct count mappings now require a scoped measure definition, including one-field sums. Field existence does not prove deaths, casualties, crashes or units. Explicit structured definitions and a bounded whole-definition grammar are supported; unknown/rate/indicator/conditional definitions do not become counts. Pinned implementation-reviewed PDF interpretations are discoverable in specific source knowledge queries and valid only for their exact dictionary hash, dataset, key/grain and coverage. They require registered applicable source evidence and citations in each task; they are not automatic source admission or proof of upload provenance.

Policy 18 retains `LOOKUP_ADMISSION_NOT_INTEGRATED` as a system-owned preflight
blocker. New physical lookup replay diagnostics can establish exact output/parent
lineage equality, but cannot resolve this semantic blocker or authorize full
execution/publication. Parent field/CRS/category and scoped CSVW relation reviews
now contribute diagnostic evidence after the same original receipt/hash checks.
Count populations, omission checks and real-source acceptance still require
implementation. More quotations or a model assertion do not complete those
system capabilities. Existing workers and historical attempts are not migrated
by these source changes; r9 is an explicitly selected isolated test image.
