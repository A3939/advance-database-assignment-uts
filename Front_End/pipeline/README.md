# ARSIA isolated import laboratory

This is **LOCAL TEST** software. It writes only its dedicated PostgreSQL database
and its configured data root (`artifacts/imports-local` for the normal laboratory, a separately owned root for acceptance). Original files, the historical course database
and website snapshot bytes remain unchanged. Local integration releases let the
existing Overview, Analytics, Data, Ask AI and Studio pages read imported sources
through `/api/data/*`. Explicit `official-v1` historical links retain their original
snapshot semantics; published release IDs are immutable.

The current autonomous implementation supersedes the older mapping-assistance
workflow documented in [ACCEPTANCE.md](ACCEPTANCE.md). Current source evidence
and verification status are in [AUTONOMOUS_VALIDATION.md](AUTONOMOUS_VALIDATION.md).
Do not interpret historical fixture success as real autonomous-source acceptance.

Use Python 3.12+ and the running local Docker engine. From `ARSIA/pipeline`:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
# Only for initial normal-laboratory setup, after confirming no task uses this tag:
docker build -f sandbox/Dockerfile -t arsia-import-adapter:3 .
.venv/bin/python -m arsia_pipeline.dev up
.venv/bin/python -m arsia_pipeline.dev status
.venv/bin/python -m pytest -q
```

`up` verifies the already installed PostgreSQL 16.15 image by its local image ID,
creates only this workspace's named container and volume, publishes PostgreSQL
on a random **loopback** port, and initializes a database carrying a random
instance marker. Unknown containers, volumes, and databases are refused.
The API runs on a private Unix socket, with no new website port.
The existing Next.js preview remains on port 3100. Its configured model service
is also used by the import worker through an authenticated loopback gateway.
The model key stays in Next.js; the worker's private gateway token stays in the
0600 runtime file. No model key or database credential enters generated Python.

The private `runtime.json` holds `socket_path` and DB connection information.
Do not print or commit it. macOS socket length restrictions require a short
`/tmp/arsia-imports-<workspacehash>/api.sock` path; its parent is 0700 and socket
0600. Configuration, credentials, and logs are private local artifacts.

After editing Python code, use:

```sh
.venv/bin/python -m arsia_pipeline.dev restart
```

This restarts only this laboratory's API and worker and retains PostgreSQL.
First check `/api/imports/health` and the job list; do not restart while a job or
integration verifier is using it. To stop the laboratory
and retain all data, use `dev stop`. It verifies process cwd/command and Docker
ownership labels; it never stops unrelated processes. No destructive purge
command is provided.

## Codex runtime

The opt-in Codex engine and its local isolation boundary are documented in
[CODEX_RUNTIME.md](CODEX_RUNTIME.md). Real experiments retain separate test databases
and never replace the website's current release. Historical foundation settings
remain documented in [AGENT_FOUNDATIONS.md](AGENT_FOUNDATIONS.md).

## Durable execution

Jobs, attempts, and events live in PostgreSQL. A session advisory lock limits
heavy execution to one worker. Candidate canonical JSONL is streamed into real
database tables with COPY, reconciled with the expected crash metrics, and
published in the same transaction as the job's terminal result. An immutable
release maps each source to a batch; updating one source preserves other sources.
Old release IDs remain readable. QA failure/cancellation/COPY failure roll back
candidate rows and preserve the old release. Identical current fingerprints give
`no_change`; a request ID with different creation parameters returns 409.

Cancellation can be recorded during COPY (the API uses NO KEY UPDATE to avoid
the batch foreign key's KEY SHARE lock), and publication checks it under a final
row lock. Once publication wins, cancellation returns 409. A lost commit reply
is resolved from committed job state. Worker loss releases the same PostgreSQL
session used for publication, so its uncommitted candidate is rolled back.
On restart, unfinished attempts are retained as interrupted and requeued from
immutable uploads, with at most three automatic crash recoveries per job. Manual
retries and cancellations do not consume that separate allowance. This is safe restart,
not resuming halfway through a database transaction.

Upload limits: 512 MiB/file, 1 GiB/job, 12 files, 4 GiB pending-upload quota.
Upload/storage reservation is serialized; a simultaneous upload can return 409
and be retried. Partial files are removed on request failure/disconnect.
Before processing, free space must exceed the larger of 2 GiB and eight times
uploaded bytes. This is a conservative guard, not a measured capacity guarantee.

## Tests and evidence

Ordinary pytest refuses real model transport and skips DB modules before binding
unless both an explicit runtime and regression marker exist. It never borrows the
normal laboratory. `verify_isolated_regressions.py` creates a new managed
PostgreSQL container/database per selected module and starts a cold pytest
process with that immutable runtime. The persisted instance marker, managed
storage ownership and dedicated-module flag are checked before writes. `keep-full`
retains evidence and the stopped container/volume, including failures.

From the project root, using an already reviewed locally named executor image:

```sh
PYTHONPATH=pipeline pipeline/.venv/bin/python pipeline/tools/verify_isolated_regressions.py \
  --new-managed-session --storage-policy keep-full \
  --output /absolute/new-evidence-directory \
  --executor-image arsia-import-adapter:YOUR-REVIEWED-LOCAL-TAG \
  --test pipeline/tests/test_unified_publication.py
```

For ordinary executor tests pass `--executor-image` to pytest explicitly; it is
resolved to an immutable image ID for that process. Do not rebuild a shared image
tag while imports are using it. Real model acceptance is separately opted in and
uses existing finite policy budgets, never the ordinary pytest entry.

Uploads and attempt outputs stay below `artifacts/imports-local`. `/evidence`
returns metadata/QA/attempt history, never canonical or original personal rows.
Logs must not contain secrets or source records. Processing source hashes and
profile provenance are supplied by the deterministic processing layer.

## Autonomous source onboarding

Open Imports, choose CSV/XLSX/XLS/ZIP/JSON/GeoJSON files and optional PDF/text
dictionaries, and click **Upload & run**. No mapping JSON is required. A single
durable Python worker inspects the bundle, discovers official evidence, creates
or reuses a versioned Python adapter, runs sample and full candidates, and invokes
independent QA before registration and atomic publication. Closing the page does
not cancel the job. Explicit Cancel stops it before publication; a published
release cannot be cancelled retroactively.

When a required meaning or actual source defect cannot be resolved, the job keeps
its transcript, code versions, source receipts and attempts and asks a specific
question. Add the requested document or plain-language information in Imports,
then resume. Providing information is not permission to override QA. The old
reviewed `generic-v1` mapping editor remains under Advanced for compatibility.

The [canonical-v2/SDK contract](AUTONOMOUS_CONTRACT.md) models crashes, traffic
units, casualties and aggregate observations separately. Source identity is not
the jurisdiction. Different or overlapping sources are shown separately, with
source-specific definitions and capability gaps; they are not silently added.
Unknown counts remain null, unavailable metrics remain unsupported, and empty
supported selections are no_results. A fatal crash is never treated as one death.

Generated code runs only in `arsia-import-adapter:2`, pinned to its actual image ID
per run: no network, no host project mount, no Docker socket, no secrets, read-only
inputs/root filesystem, unprivileged UID, bounded CPU/RAM/PIDs/time/output. Only
task input/output directories are mounted. Full exception text stays local;
bounded error classifications and line numbers are returned to the model. The
trusted worker owns Docker; there is no host-code execution fallback.

The trusted runtime's optional `executor_limits` config controls seconds, memory,
CPU, PID and output bounds within enforced ceilings. Defaults are 900 seconds,
2 GiB RAM, 2 CPUs, 64 PIDs and 4 GiB output per run. A cumulative 12 GiB job
artifact budget spans retries; an additional 1 GiB free-disk reserve is checked
during execution. Reaching a limit stops work and retains earlier evidence.
Neither uploaded JSON nor generated Python can change these limits.

Trusted QA re-reads original files independently, checks every canonical row,
keys/relationships/applicable source-declared totals, records and exact hashes,
then the loader checks actual PostgreSQL results in the publication transaction.
Sample results never authorize publication. Adapter code, executed contract,
input bytes, image and QA policy identify a version. A changed contract/code
requires re-execution and full validation. Snapshot, date-partition replacement
and stable-key incremental updates have distinct preservation rules.

## Optional Linux Compose rehearsal

`Dockerfile` and `compose.local.yaml` describe a **separate legacy deterministic
pipeline rehearsal**, not the complete autonomous runtime;
they are not used by `dev up` and have not been deployed to a VPS. The Compose
project has independent names/volumes, no published DB or API port, resource
limits, log rotation, and a private socket volume. Set
`ARSIA_IMPORT_PASSWORD_FILE` to a dedicated private file with a random password
of at least 24 characters. Linux UID 10001 must be able to read that secret.
The optional Next service would need the socket volume and matching UID access;
this file intentionally does not deploy or replace the existing Next website.
Its worker has no Docker execution service or Next model gateway and therefore
must not be used to claim autonomous Agent deployment readiness. See
[deployment/README.md](deployment/README.md) for the prepared single-host layout,
service templates, executor boundary and unverified deployment work.

Before production: separate migration/loader/reader DB credentials (the current
local laboratory account owns its dedicated DB), versioned schema upgrades,
authentication, HTTPS, quotas/retention policy, consistent off-host DB + artifact
backups with restore drills, and measured Linux capacity are still required.
The initial local implementation is not a production deployment claim.

## Current acceptance and supported sources

Read [ACCEPTANCE.md](ACCEPTANCE.md) for the dated full-volume, failure-recovery,
AI-assisted synthetic fixture and protected-data evidence. The seven native
files are supported through three independently publishable pinned profiles:
NSW (two XLSX), VIC (four CSV), and QLD (one CSV). Native source definitions,
exception identities and original author attribution are under
[arsia_pipeline/profiles](arsia_pipeline/profiles/README.md).

The previous optional manual path uses a declarative `generic-v1` contract; the
[WA example](examples/wa-profile.json) is fictional and not an approved real WA
government schema. It declares complete keys, relationships, dates, severity,
counts, source evidence and analysis years. CSV and XLSX individual-crash tables
are supported. Unknown definitions or failed QA pause instead of being guessed.
Its schema-assistance draft still requires review; this does not apply to
autonomous canonical-v2 admission, which is decided by trusted policy and QA.

The autonomous path reads dictionaries/PDFs, supports legacy XLS and structured
JSON, transforms coordinates only with documented CRS, and uses independently
verified generated Python. Frozen native baseline profiles remain reproducible;
changed bytes cannot bypass their exact exception policy by selecting generic.
Production access and server deployment remain outside this task's execution.

The local engine deliberately uses bounded SQLite relationship indexes and
streams Canonical rows into isolated PostgreSQL. It retains original bytes and
source policy, but does not run the old Raw/Vault/DW implementation or E SQL FP1.
Its fingerprints and acceptance claims are separate. Native integer results are
checked against the unchanged website snapshot. Generic unknown totals remain
null if any component is unknown; this conservative rule is explicit and tested.

## Current acceptance and compatibility boundaries

[2026-10-03 integration ledger](../docs/INTEGRATED-OPTIMIZATION-20261003.md)
records the isolated source snapshot, official input hashes, current F/K status,
failed runs and outstanding work. Existing historical acceptance is not silently
upgraded when trusted code changes. The Python wheel includes fixed CLDR/TZif
resources and licences; validate a built wheel outside the source tree.

Complex host parsers use a fixed worker process with CPU, wall, output and memory
limits, prompt cancellation and parent ownership checks. macOS memory enforcement
samples RSS every 100 ms and can overshoot transiently; it is not a Linux hard
address-space limit. Parser workers are trusted code, not filesystem sandboxes.

For ArcGIS ordinary Date fields, explicit fixed IANA + Windows no-DST metadata can
be accepted after interval-wide standard-offset comparison using pinned TZif
transitions and its POSIX footer. No state-specific timezone fallback exists.
Unknown timezone, unsupported field overrides and actual offset conflicts remain
blocked. A bounded query is an observation set; completeness and deletion rights
are independent checks.
