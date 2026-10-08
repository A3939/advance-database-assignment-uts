# Local import development contract

This development feature is an isolated laboratory. It MUST NOT write the
website's existing `data/`, snapshots, original source files, or any existing
database. No production publishing or GitHub operations are performed.

## Components

- `pipeline/arsia_pipeline`: Python API, durable PostgreSQL jobs, worker, source
  profiles and deterministic processing.
- `pipeline/.venv`: ignored local interpreter/dependencies.
- `artifacts/imports-local`: ignored runtime config, socket, uploads and evidence.
- Next.js `/api/imports/*`: loopback-only streaming bridge to the local API socket.
- `/imports`: isolated upload/workflow/results UI; no changes to `/api/data/*`.

## HTTP protocol (snake_case JSON)

- `GET /health`: `{status, mode:"local-test", worker, capabilities}`.
- `GET /jobs`: `{jobs:[Job]}`.
- `POST /jobs`: `{label?, source_hint?, request_id?}` -> Job.
- `PUT /jobs/{id}/files?filename=...`: raw body, streaming, -> Job.
- `POST /jobs/{id}/submit`: `{profile?}` -> Job. Optional reviewed generic profile.
- `GET /jobs/{id}` -> Job.
- `POST /jobs/{id}/cancel` and `/retry` -> Job.
- `GET /jobs/{id}/evidence` -> evidence JSON, never raw personal records.
- `GET /catalog` -> `{release_id, sources:[{source_id,batch_id,job_id,summary,...}]}`.
- `GET /reports?source_id=...&release_id=...` -> published aggregate result.

Job: `{id,label,status,stage,message,created_at,updated_at,files,events,
source_id?,profile_id?,batch_id?,release_id?,result?,qa?,questions?,error?,attempt}`.
File: `{id,name,size,sha256,role?,format?}`. Event: `{at,stage,message}`.
Statuses: uploading, queued, profiling, needs_input, processing, validating,
publishing, succeeded, no_change, failed, cancel_requested, cancelled, recovering.
Results and all UI copy explicitly describe LOCAL TEST publications.

## Processing interface

`arsia_pipeline.processing.process_bundle(files, work_dir, options, progress,
check_cancelled) -> dict`.

- files: `{id,name,path,sha256,size}` stored immutable regular files.
- work_dir: new attempt-owned directory; no writes outside it.
- options: `{source_hint?,profile?}`.
- progress(stage, message, **details): bounded metadata, no personal payloads.
- check_cancelled(): raises cancellation if requested; called between chunks.
- result: `{source_id,profile_id,profile_version,fingerprint,summary,trend,
  severity,units,limitations,qa,files,evidence,canonical_path,units_path?}`.
- canonical_path: JSONL of normalized crash rows: `{record_id,year,month,
  severity,fatalities,casualties,...}`; no fabricated identifiers/counts.
- qa: `[{code,status:"pass"|"limited"|"block",message,metrics?}]`.
- `NeedsInput(message, questions, details?)` stops before publication.
- `ValidationFailure(message, qa, details?)` retains diagnostics, prevents publish.
- `ImportCancelled` interrupts work before any publication.
- `processing.py` routes recognized native sources to `native.py` and reviewed
  generic profiles to `generic.py`. The coordinator owns canonical database
  insertion, atomic source-release publication and lifecycle state.

Full file bytes and semantic rules enter fingerprints; UUIDs and timestamps do
not. Publication replaces only the selected source in an immutable release map.
Known failed/cancelled work does not replace an older published result.
Worker loss uses database locks and committed outcomes, not browser state.

## Ownership during implementation

- Processing agent: `native.py`, `readers.py`, source reference profiles and
  native tests only.
- Backend agent: API, store/schema, worker, CLI/dev launcher, Compose, dependency
  files and backend tests. Import processing interface lazily to allow parallel work.
- Website agent: new import services/components/styles, bridge routes, imports
  page and browser tests. Do not edit existing dirty shared modules.
- Root: `processing.py`, `generic.py`, shared errors, integration, independent
  result comparison, documentation and final verification.
