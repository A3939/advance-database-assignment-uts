"""Private Unix-socket API. Only the loopback Next.js bridge exposes it."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg.types.json import Jsonb

from .config import read_config
from . import store

app = FastAPI(title="ARSIA isolated LOCAL TEST imports", docs_url=None, redoc_url=None)
# Trusted tests may install a synchronization hook in their own process only.
# It is not configurable through request data, environment or runtime JSON.
_TEST_STORAGE_HOOK = None
def _storage_barrier(phase):
    if _TEST_STORAGE_HOOK is not None:_TEST_STORAGE_HOOK(phase)

MAX_FILE = 512 * 1024**2
MAX_JOB = 1024**3
MAX_FILES = 12
MAX_PENDING = 4 * 1024**3


class NewJob(BaseModel):
    label: str = Field(default="Local test import", max_length=200)
    source_hint: str | None = Field(default=None, max_length=100)
    request_id: str | None = Field(default=None, max_length=100)


class Submit(BaseModel):
    profile: dict | None = None
    answers: str | None = Field(default=None, max_length=12000)


def require_job(job_id):
    result = store.get_job(job_id)
    if not result:
        raise HTTPException(404, "Import job not found")
    return result


def storage_write_guard(conn, cfg):
    if cfg.get('storage_policy',{}).get('enabled') is not True:return
    if not conn.execute('SELECT pg_try_advisory_xact_lock(%s) AS locked',(store.LOCK+1,)).fetchone()['locked']:
        raise HTTPException(409,'Test storage maintenance or another upload is active')
    from .input_store import assert_accepting
    from .storage_lifecycle import StorageError
    try:assert_accepting(cfg)
    except StorageError as exc:
        raise HTTPException(409,{'code':exc.code,'message':str(exc)}) from None


@app.get("/health")
def health():
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM worker_state").fetchone()
        live = bool(row and (datetime.now(timezone.utc) - row["heartbeat_at"]).total_seconds() < 20)
    return {"status": "ok", "mode": "local-test", "worker": {
        "alive": live, "heartbeat_at": row["heartbeat_at"].isoformat() if row else None,
        "active_job_id": str(row["active_job_id"]) if row and row["active_job_id"] else None},
        "capabilities": {"formats": ["csv", "xlsx", "xls", "zip", "json", "geojson"], "autonomous_agent": True, "max_file_bytes": MAX_FILE,
                         "max_job_bytes": MAX_JOB, "max_files": MAX_FILES, "concurrency": 1,
                         "storage": read_config().get('storage_policy',{}).get('enabled') is True,
                         "production_publication": False}}


@app.get('/storage')
def storage_status():
    cfg=read_config()
    if cfg.get('storage_policy',{}).get('enabled') is not True:
        return {'managed':False,'measurement_scope':'unmanaged legacy instance','groups':{},'docker_bytes':None}
    from .storage_lifecycle import Ledger
    return Ledger(cfg,read_only=True).snapshot()


@app.get('/jobs/{job_id}/storage')
def job_storage_status(job_id:UUID):
    require_job(job_id)
    cfg=read_config()
    if cfg.get('storage_policy',{}).get('enabled') is not True:
        return {'managed':False,'measurement_scope':'unmanaged legacy instance','groups':{},'docker_bytes':None}
    from .storage_lifecycle import Ledger
    return Ledger(cfg,read_only=True).snapshot(str(job_id))


@app.get("/jobs")
def jobs():
    with store.connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()
    return {"jobs": [store.clean_job(r) for r in rows]}


@app.post("/jobs")
def new_job(body: NewJob):
    job_id = uuid4()
    with store.connect() as conn, conn.transaction():
        storage_write_guard(conn, read_config())
        row = conn.execute("""INSERT INTO jobs(id,request_id,label,status,stage,message,options,events)
            VALUES(%s,%s,%s,'uploading','uploading',%s,%s,%s)
            ON CONFLICT(request_id) DO UPDATE SET request_id=excluded.request_id RETURNING *""",
            (job_id, body.request_id, body.label, "Upload files for an isolated LOCAL TEST.",
             Jsonb({"source_hint": body.source_hint}),
             Jsonb([store.event("uploading", "LOCAL TEST job created")]))).fetchone()
    if body.request_id and (row["label"] != body.label or row["options"].get("source_hint") != body.source_hint):
        raise HTTPException(409, "This request_id was already used with different job parameters")
    return store.clean_job(row)


@app.get("/jobs/{job_id}")
def get_job(job_id: UUID):
    job = require_job(job_id)
    from .agent_status import status
    progress = status(job)
    return {**job, "agent": progress} if progress else job


@app.put("/jobs/{job_id}/files")
async def upload(job_id: UUID, filename: str, request: Request):
    if not filename or filename != Path(filename).name or "\\" in filename or len(filename) > 200 or any(ord(c)<32 for c in filename):
        raise HTTPException(400, "Use a plain filename without directory components")
    if Path(filename).suffix.lower() not in {".csv", ".xlsx", ".xls", ".zip", ".json", ".geojson", ".txt", ".md", ".pdf"}:
        raise HTTPException(400, "Supported files: CSV, Excel and optional JSON/text/PDF source documentation")
    cfg = read_config()
    from . import input_store
    managed_cas = input_store.active(cfg)
    receipt = None
    folder = Path(cfg["data_root"]) / "uploads" / str(job_id)
    file_id = uuid4().hex
    partial, final = folder / (file_id + ".part"), folder / (file_id + Path(filename).suffix.lower())
    committed = False
    try:
        with store.connect() as conn, conn.transaction():
            storage_write_guard(conn, cfg)
            # NOWAIT avoids a slow uploader monopolizing another request/event loop.
            row = conn.execute("SELECT * FROM jobs WHERE id=%s FOR UPDATE NOWAIT", (job_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Import job not found")
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            if row["status"] not in {"uploading", "needs_input"}:
                raise HTTPException(409, "Files are immutable after the job is submitted")
            if len(row["files"]) >= MAX_FILES:
                raise HTTPException(413, "This job has reached its file-count limit")
            used = sum(f["size"] for f in row["files"])
            if not conn.execute("SELECT pg_try_advisory_xact_lock(%s) AS locked", (store.LOCK + 1,)).fetchone()["locked"]:
                raise HTTPException(409, "Another upload is reserving storage; retry this upload shortly")
            pending = conn.execute("""SELECT coalesce(sum((f->>'size')::bigint),0) AS size
                FROM jobs CROSS JOIN LATERAL jsonb_array_elements(files) f
                WHERE status NOT IN ('succeeded','no_change','failed','cancelled')""").fetchone()["size"]
            declared = request.headers.get("content-length")
            if declared and (int(declared)>MAX_FILE or used+int(declared)>MAX_JOB):
                raise HTTPException(413, "Upload exceeds file/job size limit")
            if shutil.disk_usage(folder).free < MAX_FILE + 2*1024**3:
                raise HTTPException(507, "Insufficient disk reserve for another upload")
            if managed_cas:
                from .upload_gc import begin
                begin(cfg,partial,job_id,file_id)
            size, digest = 0, hashlib.sha256()
            with partial.open("xb") as handle:
                os.chmod(partial, 0o600)
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_FILE or used+size>MAX_JOB:
                        raise HTTPException(413, "Upload exceeds file/job size limit")
                    if pending+size>MAX_PENDING:
                        raise HTTPException(413, "Global pending-upload quota reached; finish or cancel earlier jobs")
                    digest.update(chunk)
                    handle.write(chunk)
                    if managed_cas and _TEST_STORAGE_HOOK is not None:
                        handle.flush();os.fsync(handle.fileno());_storage_barrier('upload_partial')
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0:
                raise HTTPException(400, "Empty files cannot be imported")
            receipt = {"id": file_id, "name": filename, "path": str(final),
                                      "size": size, "sha256": digest.hexdigest(),
                                      "format": Path(filename).suffix.lower().lstrip(".")}
            if managed_cas:
                receipt = input_store.publish(cfg, partial, {**receipt, 'job_id':str(job_id)})
                _storage_barrier('upload_pending_commit')
            else:
                partial.rename(final)
            files = row["files"] + [receipt]
            conn.execute("UPDATE jobs SET files=%s,updated_at=now(),events=events||%s::jsonb WHERE id=%s",
                         (Jsonb(files), Jsonb([store.event("uploading", f"Received {filename}", size=size)]), job_id))
        committed = True
        if managed_cas:
            _storage_barrier('upload_sql_committed')
            # Audit append failure cannot undo an already committed upload.
            try: input_store.committed(cfg,receipt)
            except Exception: pass
    except Exception as exc:
        import psycopg
        import errno
        if isinstance(exc,OSError) and exc.errno==errno.ENOSPC:
            raise HTTPException(507,{'code':'STORAGE_SPACE','message':'Upload storage is full; existing content retained'}) from None
        from .storage_lifecycle import StorageError
        if isinstance(exc, StorageError):
            raise HTTPException(507 if exc.code in {'STORAGE_SPACE','STORAGE_BUDGET'} else 409,
                                {'code':exc.code,'message':str(exc)}) from None
        if isinstance(exc, psycopg.errors.LockNotAvailable):
            raise HTTPException(409, "Another upload or change is in progress for this job") from None
        raise
    finally:
        partial.unlink(missing_ok=True)
        if not committed and not managed_cas:
            final.unlink(missing_ok=True)
    return require_job(job_id)


def enqueue(job_id, body, retry=False):
    with store.connect() as conn, conn.transaction():
        from .input_store import assert_accepting, resolve
        cfg = read_config()
        storage_write_guard(conn, cfg)
        row = conn.execute("SELECT * FROM jobs WHERE id=%s FOR UPDATE", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Import job not found")
        allowed = {"failed", "cancelled", "needs_input"} if retry else {"uploading", "needs_input"}
        if row["status"] not in allowed:
            raise HTTPException(409, "This job cannot be submitted/retried in its current state")
        if not row["files"]:
            raise HTTPException(400, "Upload at least one data file")
        if cfg.get('storage_policy',{}).get('enabled'):
            from .storage_lifecycle import StorageError
            try:
                for receipt in row['files']: resolve(cfg,receipt)
            except StorageError as exc:
                raise HTTPException(409,{'code':exc.code,'message':str(exc)}) from None
        if row["status"] in {"failed", "cancelled"}:
            if not conn.execute("SELECT pg_try_advisory_xact_lock(%s) AS locked", (store.LOCK + 1,)).fetchone()["locked"]:
                raise HTTPException(409, "Storage reservation is busy; retry shortly")
            pending = conn.execute("""SELECT coalesce(sum((f->>'size')::bigint),0) AS size
                FROM jobs CROSS JOIN LATERAL jsonb_array_elements(files) f
                WHERE status NOT IN ('succeeded','no_change','failed','cancelled')""").fetchone()["size"]
            if pending + sum(f["size"] for f in row["files"]) > MAX_PENDING:
                raise HTTPException(413, "Global pending-upload quota reached; cannot requeue this job yet")
        options = dict(row["options"])
        if body.profile is not None:
            options["profile"] = body.profile
        if body.answers is not None:
            options["answers"] = body.answers
        conn.execute("""UPDATE jobs SET status='queued',stage='queued',message='Queued for LOCAL TEST processing',
            options=%s,error=NULL,questions=NULL,updated_at=now(),events=events||%s::jsonb WHERE id=%s""",
            (Jsonb(options), Jsonb([store.event("queued", "Queued for LOCAL TEST processing")]), job_id))
    return require_job(job_id)


@app.post("/jobs/{job_id}/submit")
def submit(job_id: UUID, body: Submit = Submit()):
    return enqueue(job_id, body)


@app.post("/jobs/{job_id}/retry")
def retry(job_id: UUID, body: Submit = Submit()):
    return enqueue(job_id, body, True)


@app.post("/jobs/{job_id}/cancel")
def cancel(job_id: UUID):
    with store.connect() as conn, conn.transaction():
        # Batch insertion holds a foreign-key KEY SHARE lock on this job.
        # NO KEY UPDATE allows cancellation while COPY is still in progress.
        row = conn.execute("SELECT status FROM jobs WHERE id=%s FOR NO KEY UPDATE", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Import job not found")
        if row["status"] in {"succeeded", "no_change"}:
            raise HTTPException(409, "A published LOCAL TEST cannot be cancelled")
        status = "cancel_requested" if row["status"] in store.ACTIVE else "cancelled"
        conn.execute("UPDATE jobs SET status=%s,stage=%s,message=%s,updated_at=now(),events=events||%s::jsonb WHERE id=%s",
            (status, status, "Cancellation requested", Jsonb([store.event(status, "Cancellation requested")]), job_id))
        if status == "cancelled":
            conn.execute("UPDATE agent_sessions SET status='cancelled',updated_at=now() WHERE job_id=%s", (job_id,))
    return require_job(job_id)


@app.get("/jobs/{job_id}/evidence")
def evidence(job_id: UUID):
    job = require_job(job_id)
    with store.connect() as conn:
        attempts = conn.execute("SELECT id,number,started_at,finished_at,status,error FROM attempts WHERE job_id=%s ORDER BY number", (job_id,)).fetchall()
        session = conn.execute("SELECT id,status,model_calls,tool_calls,correction_count,compute_seconds,created_at,updated_at FROM agent_sessions WHERE job_id=%s", (job_id,)).fetchone()
        steps = conn.execute("SELECT id,kind,name,status,arguments,result,created_at,finished_at FROM agent_steps WHERE session_id=%s ORDER BY id", (session["id"],)).fetchall() if session else []
    from .agent import safe
    # Never expose raw/canonical files or server paths through evidence downloads.
    return {"mode": "local-test", "job": job, "attempts": attempts, "agent": {"session": session, "steps": safe(steps)},
            "boundary": "Local test only; original website snapshots and production data are unchanged"}


@app.get("/catalog")
def catalog(release_id: UUID | None = None):
    from .query import catalog as read_catalog
    try:
        return read_catalog(release_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None


@app.get("/query")
def query_data(request: Request, source_id: str, release_id: UUID, include_units: bool = True):
    from .query import query
    try:
        return query(source_id, release_id, request.query_params.get("from", ""), request.query_params.get("to", ""), include_units=include_units)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@app.get("/reports")
def reports(source_id: str, release_id: UUID | None = None):
    with store.connect() as conn:
        if release_id:
            row = conn.execute("SELECT id,sources FROM releases WHERE id=%s", (release_id,)).fetchone()
        else:
            row = conn.execute("SELECT r.id,r.sources FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()
        if not row or source_id not in row["sources"]:
            raise HTTPException(404, "This source has no publication in the requested LOCAL TEST release")
        batch = row["sources"][source_id]
        result = conn.execute("SELECT result FROM batches WHERE id=%s", (batch,)).fetchone()["result"]
    return {**result, "release_id": str(row["id"]), "batch_id": batch, "mode": "local-test"}
