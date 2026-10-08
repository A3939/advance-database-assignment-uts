# Single-host deployment preparation

**Prepared configuration; no remote server deployment was performed.** The tested
runtime is the existing macOS site on loopback port 3100, a host Python worker/API,
a dedicated PostgreSQL container and per-run isolated adapter containers.

Keep that topology for the first Linux rehearsal. A long-running host worker owns
durable scheduling and launches one bounded adapter container at a time. A queue
service is unnecessary at this concurrency. The database may later be managed
PostgreSQL. The website and import API may be packaged separately, but container
packaging does not replace the isolation or atomic publication protocol.

## Prepared files

- `../sandbox/Dockerfile`: reproducible generated-code executor image. Build it
  with `docker build -f sandbox/Dockerfile -t arsia-import-adapter:2 .` from pipeline.
- `../Dockerfile` and `../compose.local.yaml`: independent **legacy deterministic**
  DB/API/worker rehearsal. It intentionally has no host Docker socket or model
  gateway. It does not run the new autonomous worker end to end.
- `arsia-import-api.service` and `arsia-import-worker.service`: Linux host-service
  templates for a dedicated `arsia` account and installation at `/srv/arsia`.
  Copy/edit them only during an explicitly scheduled server rehearsal. Do not
  install them alongside the local `dev up` launcher; two process supervisors
  should not own the same API/worker.

For a Linux rehearsal, install Python 3.12+, the pinned Python requirements, the
application's locked Node dependencies, Docker and the executor image. Initialize
the isolated database/configuration with the trusted lifecycle code before
starting the service templates. The lifecycle launcher's current PostgreSQL image
is pinned to the image already verified locally; verify/pin an appropriate
PostgreSQL 16 image on the target CPU architecture. Never substitute production
credentials or reuse a database lacking the expected instance marker.

The trusted account's Docker CLI must already use its intended daemon/context.
A dedicated rootless daemon is preferable for a single-host rehearsal. Generated
containers never receive the socket, CLI credentials, model key or database DSN.
Only the trusted executor can select image, mounts, namespace and limits. If a
containerized trusted worker is introduced later, retain identical absolute bind
paths on daemon and worker hosts or use a separate controlled executor RPC; do
not expose arbitrary Docker operations to the model.

The Next server must run on the same host at `127.0.0.1:3100` for the current model
gateway. It reads the private `artifacts/imports-local/runtime.json`; the API binds
the private `/tmp/arsia-imports-<workspacehash>/api.sock`. The account must have
access to those files. Credentials remain outside source control. Do not print
runtime files, copy local credentials to a server or pass them into adapter
containers. The current HTTP bridge intentionally accepts only local origins;
remote Imports access needs application authentication and an explicitly reviewed
origin/proxy policy before exposure. A public reverse proxy alone is insufficient.

## Rehearsal and release gates

Run Python/TypeScript tests, all real executor tests, a temporary PostgreSQL
publication test, original three-source regression and an actual model upload
on the target host. Confirm browser-close persistence, cancellation/recovery,
timeouts/OOM, private-address fetch denial and full source-specific query/AI/Studio
agreement. Review exact image IDs, dependency versions and resource measurements.

Test backup/restore of PostgreSQL **and** the immutable uploads, evidence, code and
run artifacts together. A database-only backup does not preserve reproducibility.
Define retained versions, disk quotas and operator cleanup before sustained use.
Split migration/loader/reader database roles before production; the current lab
account owns only its isolated test database. Authentication, HTTPS, secret
rotation, external backups, Linux resource measurements and restore drills are
not claimed as completed by this local task.

Use the existing local commands for this workstation:

```sh
.venv/bin/python -m arsia_pipeline.dev status
# Check no active jobs before restart.
.venv/bin/python -m arsia_pipeline.dev restart
# Stop only this owned lab, preserving its database and artifacts.
.venv/bin/python -m arsia_pipeline.dev stop
```

SIGTERM preserves an interrupted attempt; restarting the worker requeues from
immutable inputs and saved Agent evidence. It does not resume half a COPY
transaction. Never run global Docker prune/kill, remove the lab volume, or reset
the database as a recovery step.

On startup, the worker acquires its marked database's global scheduling lock and
checks orphan containers against the exact job/attempt, host ownership receipt,
receipt hash, labels and bind mounts. Only a verified incomplete container is
removed, by immutable ID, with an audit retained. This requires the worker to
restart: the prepared Restart=on-failure unit supplies that supervision during a
future Linux rehearsal, but it has not been installed or tested there. There is
no independent orphan timeout service when the worker remains down.

The current private API socket and runtime files require matching owner access
for the trusted API, worker and Next server; group membership alone does not
grant access to a mode-0600 socket. Verify the actual Linux account/paths before
starting services. Generated code retains a separate unprivileged container UID
and never receives these private host files.

An 8 GiB RAM / 75 GiB disk server is a deployment target, not a measured capacity
claim. The local 2 GiB per-adapter limit and 12 GiB cumulative per-job artifact
budget are safety ceilings, not expected peak usage or retention policy. Measure
the whole Next/API/worker/PostgreSQL/adapter stack and retained original/run/WAL
bytes on the target host before assigning concurrency and retention. Historical
macOS ru_maxrss measurements must not be treated as Linux KiB measurements or
as the sum of live process/container memory.

Use [../FINAL_VALIDATION_FRAMEWORK.md](../FINAL_VALIDATION_FRAMEWORK.md) to separate
confirmed local evidence from pending source-version, lifecycle and deployment
claims in the final report.
