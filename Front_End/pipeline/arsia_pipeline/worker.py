"""One heavy importer; durable attempts and atomic, source-scoped publication."""
from datetime import datetime, timezone
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import signal
import shutil
import threading
import time
from uuid import uuid4

from psycopg.types.json import Jsonb
from psycopg.pq import TransactionStatus

from . import store
from .config import inside, read_config, output_path
from .errors import ImportCancelled, NeedsInput, ValidationFailure
from .reconcile import verify_candidate


class WorkerInterrupted(BaseException):
    pass


class CancellationCheck:
    """Local stop is immediate; external cancellation is polled at most 4 Hz.

    Publication still locks/rechecks job state inside its final transaction.
    Stage boundaries can force a fresh poll; row count does not control IO.
    """
    def __init__(self, job_id, stop, lock_conn=None, *, clock=time.monotonic):
        self.job_id, self.stop, self.lock_conn = job_id, stop, lock_conn
        self.clock, self.last_poll = clock, float('-inf')

    def __call__(self, *, force=False):
        conn = self.lock_conn
        if self.stop.is_set():
            raise WorkerInterrupted()
        if conn is not None and (conn.closed or conn.info.transaction_status == TransactionStatus.UNKNOWN):
            self.stop.set()
            raise WorkerInterrupted()
        now = self.clock()
        if not force and now - self.last_poll < .25:
            return
        if conn is not None and not conn.info.transaction_status:
            try:
                conn.execute('SELECT 1')
            except Exception:
                self.stop.set()
                raise WorkerInterrupted()
        row = store.get_job(self.job_id, internal=True)
        self.last_poll = self.clock()
        if not row or row['status'] in {'cancel_requested', 'cancelled'}:
            raise ImportCancelled()


def recover_abandoned(conn):
    """Caller owns the session lock: no previous worker can still publish."""
    with conn.transaction():
        rows = conn.execute("SELECT id,status,attempt FROM jobs WHERE status=ANY(%s) FOR UPDATE", (list(store.ACTIVE),)).fetchall()
        for row in rows:
            status = "cancelled" if row["status"] == "cancel_requested" else "queued"
            message = "Interrupted attempt recovered; safely queued from immutable inputs" if status == "queued" else "Cancellation recovered after worker loss"
            recovered = conn.execute("""SELECT count(*) AS n FROM attempts WHERE job_id=%s AND error->>'code'='worker_lost'
                AND (error->>'automatic_recovery'='true' OR
                    (NOT(error ? 'automatic_recovery') AND error->>'message'<>'Cancellation recovered after worker loss'))""",(row["id"],)).fetchone()["n"]
            if status == "queued" and recovered >= 3:
                status, message = "failed", "Automatic recovery attempt limit reached; review evidence before a manual retry"
            conn.execute("UPDATE attempts SET status='interrupted',finished_at=now(),error=%s WHERE job_id=%s AND finished_at IS NULL",
                         (Jsonb({"code": "worker_lost", "message": message,"automatic_recovery":status=="queued",
                                 "prior_automatic_recoveries":recovered}), row["id"]))
            conn.execute("""UPDATE agent_steps s SET status='interrupted',finished_at=now(),
                result=coalesce(s.result,'{}'::jsonb)||%s::jsonb FROM agent_sessions a
                WHERE s.session_id=a.id AND a.job_id=%s AND s.status='running'""",
                (Jsonb({"code": "worker_lost", "message": message}), row["id"]))
            conn.execute("UPDATE agent_sessions SET status=%s,updated_at=now() WHERE job_id=%s", ("recovering" if status == "queued" else status, row["id"]))
            conn.execute("UPDATE jobs SET status=%s,stage=%s,message=%s,updated_at=now(),events=events||%s::jsonb WHERE id=%s",
                         (status, status, message, Jsonb([store.event("recovering", message)]), row["id"]))
    return len(rows)


def claim(conn, config):
    with conn.transaction():
        row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
        if not row:
            return None
        attempt, number = uuid4(), row["attempt"] + 1
        work = output_path("attempts",str(row["id"]),str(attempt))
        work.mkdir(parents=True, mode=0o700)
        conn.execute("INSERT INTO attempts(id,job_id,number,status,work_dir) VALUES(%s,%s,%s,'running',%s)",
                     (attempt, row["id"], number, str(work)))
        conn.execute("UPDATE jobs SET status='profiling',stage='profiling',message='Inspecting immutable inputs',attempt=%s,updated_at=now(),events=events||%s::jsonb WHERE id=%s",
                     (number, Jsonb([store.event("profiling", "Attempt started", attempt=number)]), row["id"]))
        return {**row, "attempt_id": attempt, "attempt": number, "work_dir": work}


def safe_result(result):
    from .agent import safe
    return safe(result)


def publish(job, result, check_cancelled, lock_conn=None):
    if result.get("source_contract", {}).get("contract_version") == "canonical-v2":
        from .publication import publish as publish_autonomous
        return publish_autonomous(job, result, check_cancelled, lock_conn)
    from .publication_policy import (verify_deterministic, require_source_level,
        require_active_attempt, admission_level, historical_replay)
    from .publication import publication_transaction
    gate = verify_deterministic(job, result)
    with store.connect() as precheck:
        require_active_attempt(precheck, job)
    path = inside(result["canonical_path"], job["work_dir"])
    if not path.is_file():
        raise ValidationFailure("Canonical output is missing")
    public = safe_result(result)
    source, fingerprint = result["source_id"], result["fingerprint"]
    store.update_job(job["id"], "publishing", "Loading candidate rows into the isolated database; old release remains available")
    # Publication uses the SAME session that owns the global lock. Losing that
    # session also aborts its transaction, so an old worker cannot race recovery.
    with (nullcontext(lock_conn) if lock_conn is not None else store.connect()) as conn, publication_transaction(conn, job['id'], check_cancelled):
        conn.execute('SELECT pg_advisory_xact_lock(%s)', (store.LOCK,))
        require_active_attempt(conn, job)
        existing = conn.execute("SELECT id,result FROM batches WHERE source_id=%s AND fingerprint=%s", (source, fingerprint)).fetchone()
        current = conn.execute("SELECT r.id,r.sources FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()
        sources = dict(current["sources"]) if current else {}
        base = conn.execute('SELECT id,result FROM batches WHERE id=%s', (sources[source],)).fetchone() if source in sources else None
        require_source_level(result, base['result'] if base else None)
        if gate['admission_level'] == 'manual_reviewed' and conn.execute(
                'SELECT 1 FROM source_versions WHERE source_id=%s LIMIT 1', (source,)).fetchone():
            raise NeedsInput('A manually confirmed profile cannot use a registered official source identity. Choose a separate source_id.')
        replay = historical_replay(conn, result, base)
        superseded = bool(base and gate['admission_level'] == 'fixed_native' and admission_level(base['result']) == 'official_admitted')
        unchanged = bool(base and (existing or replay or superseded))
        batch = base['id'] if unchanged else uuid4()
        if unchanged:
            public = dict(base['result'])
            if admission_level(public) == 'official_admitted':
                from .publication import verify
                public['database_verification'] = verify(conn, batch, public, candidate=False)
            else:
                public['database_verification'] = verify_candidate(conn, batch, public)
        if not unchanged:
            conn.execute("INSERT INTO batches(id,job_id,source_id,fingerprint,result) VALUES(%s,%s,%s,%s,%s)",
                         (batch, job["id"], source, fingerprint, Jsonb(public)))
            with conn.cursor().copy("COPY canonical_crash(batch_id,record_id,year,month,severity,fatalities,casualties,payload) FROM STDIN") as copy:
                with path.open() as handle:
                    for index, line in enumerate(handle):
                        if index % 1000 == 0:
                            check_cancelled()
                        row = json.loads(line)
                        copy.write_row((batch, row["record_id"], row["year"], row.get("month"), row.get("severity"),
                                        row.get("fatalities"), row.get("casualties"), Jsonb(row)))
            if result.get("units_path"):
                unit_path = inside(result["units_path"], job["work_dir"])
                with conn.cursor().copy("COPY canonical_unit(batch_id,ordinal,payload) FROM STDIN") as copy:
                    with unit_path.open() as handle:
                        for index, line in enumerate(handle):
                            if index % 1000 == 0:
                                check_cancelled()
                            copy.write_row((batch, index, Jsonb(json.loads(line))))
            public["database_verification"] = verify_candidate(conn, batch, result)
            if base:
                # Legacy keys remain their declared composite record_id. A
                # confirmed profile has no authority to remove prior records.
                removals = {}
                for table in ('canonical_crash', 'canonical_unit'):
                    field = "record_id" if table == 'canonical_crash' else "payload->>'record_id'"
                    removed = conn.execute(f"SELECT count(*) AS n FROM {table} old WHERE batch_id=%s AND NOT EXISTS (SELECT 1 FROM {table} new WHERE new.batch_id=%s AND new.{field}=old.{field})", (base['id'], batch)).fetchone()['n']
                    if removed: removals[table] = removed
                if removals:
                    raise NeedsInput('This deterministic candidate lacks authority to remove previously published records.', [], {'removals': removals})
            from .publication_summary import capture
            public['query_facts'] = capture(conn, batch, public)
            conn.execute("UPDATE batches SET result=%s WHERE id=%s", (Jsonb(public), batch))
        check_cancelled()
        # Cancellation and publication race on this row. Exactly one wins.
        state = conn.execute("SELECT status FROM jobs WHERE id=%s FOR UPDATE", (job["id"],)).fetchone()
        if state["status"] == "cancel_requested":
            raise ImportCancelled()
        if unchanged:
            release_id, status = current["id"], "no_change"
        else:
            sources[source] = str(batch)
            release_id, status = uuid4(), "succeeded"
            conn.execute("INSERT INTO releases(id,sources) VALUES(%s,%s)", (release_id, Jsonb(sources)))
            conn.execute("INSERT INTO current_release(release_id) VALUES(%s) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id", (release_id,))
        message = "Identical LOCAL TEST source version is already published" if unchanged else "LOCAL TEST published; other sources retained"
        public["publication_evidence"] = {"reused_batch_id": str(batch) if unchanged else None,
            "reason": "historical_input_replay" if replay or superseded else "same_input" if unchanged else "new_candidate",
            "candidate_validation": {"publication_gate": gate, "qa": result["qa"]},
            "attempt_id": str(job["attempt_id"]), "input_fingerprint": fingerprint,
            "note": "Batch evidence refers to its original publication; this job's files and attempt identify the current submission"}
        conn.execute("""UPDATE jobs SET status=%s,stage=%s,message=%s,source_id=%s,profile_id=%s,batch_id=%s,release_id=%s,
            result=%s,qa=%s,error=NULL,questions=NULL,updated_at=now(),events=events||%s::jsonb WHERE id=%s""",
            (status, status, message, source, result["profile_id"], batch, release_id, Jsonb(public), Jsonb(result["qa"]),
             Jsonb([store.event(status, message)]), job["id"]))
        conn.execute("UPDATE attempts SET status=%s,finished_at=now() WHERE id=%s", (status, job["attempt_id"]))
        conn.execute("UPDATE agent_sessions SET status=%s,updated_at=now() WHERE job_id=%s", (status, job["id"]))
    return status


def execute(job, stop, lock_conn=None):
    check_cancelled = CancellationCheck(job['id'], stop, lock_conn)
    phase = 'intake'

    def progress(stage, message, **details):
        check_cancelled(force=True)
        status = stage if stage in {"profiling", "processing", "validating"} else "processing"
        store.update_job(job["id"], status, message[:1000], stage=stage)

    try:
        from .processing import process_bundle
        check_cancelled()
        cfg = read_config()
        if cfg.get('storage_policy',{}).get('enabled'):
            from .storage_lifecycle import Ledger, assert_budget
            from .input_store import assert_accepting, resolve
            assert_accepting(cfg)
            for receipt in job['files']: resolve(cfg,receipt)
            assert_budget(Ledger(cfg),sum(f['size'] for f in job['files'])*2)
        reserve = max(2*1024**3, sum(f["size"] for f in job["files"])*8)
        if shutil.disk_usage(job["work_dir"]).free < reserve:
            if cfg.get('storage_policy',{}).get('enabled'):
                from .storage_lifecycle import StorageError
                raise StorageError('STORAGE_SPACE','Insufficient free disk reserve; no Agent investigation was started')
            raise ValidationFailure("Insufficient free disk reserve for candidate processing")
        from .native_revision import classify_native_route
        native_route = classify_native_route(job["files"], check_cancelled)
        def investigate(exc, operation):
            from .agent import agent_process
            agent_dir = job['work_dir'] / 'agent'
            agent_dir.mkdir(exist_ok=True, mode=0o700)
            return agent_process(job['files'], agent_dir, job['options'], progress, check_cancelled, job=job,
                native_context=native_route.context,
                publisher=lambda candidate: publish(job, candidate, check_cancelled, lock_conn),
                initial_blocker=(exc, operation))
        try:
            if native_route.kind == "revision":
                raise NeedsInput("A complete native source revision requires a new independently admitted snapshot.")
            result = process_bundle(job["files"], job["work_dir"], job["options"], progress, check_cancelled)
        except NeedsInput as exc:
            from .errors import BudgetExhausted
            if isinstance(exc, BudgetExhausted) or native_route.kind == "pinned" or (job["options"].get("profile") and native_route.kind != "revision" and cfg.get('bounded_repair_v1') is not True):
                raise
            phase = 'agent'
            result = investigate(exc, 'deterministic_intake')
        check_cancelled(force=True)
        phase = 'publication'
        if not result.get('_publication_status'):
            try:
                publish(job, result, check_cancelled, lock_conn)
            except NeedsInput as exc:
                from .errors import BudgetExhausted
                # Only a deterministic candidate has no Agent session yet.
                # Never launch a second session after an autonomous stop.
                if (cfg.get('bounded_repair_v1') is not True or native_route.kind == 'pinned'
                        or isinstance(exc, BudgetExhausted) or result.get('source_contract', {}).get('contract_version') == 'canonical-v2'):
                    raise
                result = investigate(exc, 'deterministic_publication')
                if not result.get('_publication_status'):
                    publish(job, result, check_cancelled, lock_conn)
    except (NeedsInput, ValidationFailure, ImportCancelled) as exc:
        if isinstance(exc, NeedsInput):
            status, message = "needs_input", str(exc)
            fields = {"questions": exc.questions, "error": {"code": exc.code, "message": message, "details": exc.details}}
        elif isinstance(exc, ValidationFailure):
            status, message = "failed", str(exc)
            fields = {"qa": exc.qa, "error": {"code": "validation_failed", "message": message, "details": exc.details}}
        else:
            status, message = "cancelled", "Cancelled before LOCAL TEST publication"
            fields = {"error": {"code": "cancelled", "message": message}}
        if locals().get('cfg', {}).get('bounded_repair_v1') is True:
            from .repair_context import terminal_context
            fields['error']['routing'] = terminal_context(job, exc, phase,
                pinned=locals().get('native_route') is not None and native_route.kind == 'pinned')
        try:
            store.update_job(job["id"], status, message, **fields)
        except ImportCancelled:
            status, message = "cancelled", "Cancellation won while processing diagnostics were being saved"
            fields = {"error": {"code": "cancelled", "message": message}}
            store.update_job(job["id"], status, message, **fields)
        (job["work_dir"] / "failure.json").write_text(json.dumps({"status": status, **fields}, ensure_ascii=False, indent=2))
        with store.connect() as conn:
            conn.execute("UPDATE attempts SET status=%s,error=%s,finished_at=now() WHERE id=%s", (status, Jsonb(fields.get("error")), job["attempt_id"]))
            conn.execute("UPDATE agent_sessions SET status=%s,updated_at=now() WHERE job_id=%s", (status, job["id"]))
    except Exception as exc:
        # A commit acknowledgement may be lost. Consult committed state first.
        row = store.get_job(job["id"], internal=True)
        if row and row["status"] in {"succeeded", "no_change"}:
            return
        cancelled = row and row["status"] in {"cancel_requested", "cancelled"}
        status = "cancelled" if cancelled else "failed"
        error = {"code": "cancelled" if cancelled else "execution_failed", "type": type(exc).__name__,
                 "message": "Cancelled before LOCAL TEST publication" if cancelled else
                 "Processing failed; candidate transaction was rolled back. Review evidence or retry."}
        from .storage_lifecycle import StorageError
        if isinstance(exc, StorageError):
            error.update(code=exc.code, kind=exc.kind, message=str(exc), responsible_party='system')
        if locals().get('cfg', {}).get('bounded_repair_v1') is True:
            from .repair_context import terminal_context
            error['routing'] = terminal_context(job, exc, phase)
        store.update_job(job["id"], status, error["message"], error=error)
        (job["work_dir"] / "failure.json").write_text(json.dumps(error, indent=2))
        with store.connect() as conn:
            conn.execute("UPDATE attempts SET status=%s,error=%s,finished_at=now() WHERE id=%s", (status, Jsonb(error), job["attempt_id"]))
            conn.execute("UPDATE agent_sessions SET status=%s,updated_at=now() WHERE job_id=%s", (status, job["id"]))


def run(once=False):
    config = read_config()
    stop, owner = threading.Event(), uuid4().hex
    active = {"id": None}
    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
    with store.connect() as lock_conn:
        locked = lock_conn.execute("SELECT pg_try_advisory_lock(%s) AS locked", (store.LOCK,)).fetchone()["locked"]
        if not locked:
            raise RuntimeError("Another local import worker owns the global execution lock")
        from .scoped_orphans import recover_owned_orphans
        from .isolated_executor import docker
        recover_owned_orphans(lock_conn,config,docker)
        recover_abandoned(lock_conn)

        def heartbeat():
            while not stop.is_set():
                try:
                    with store.connect() as conn:
                        conn.execute("""INSERT INTO worker_state(owner,active_job_id) VALUES(%s,%s)
                            ON CONFLICT(singleton) DO UPDATE SET owner=excluded.owner,active_job_id=excluded.active_job_id,heartbeat_at=now()""", (owner, active["id"]))
                except Exception:
                    stop.set()
                stop.wait(3)
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            while not stop.is_set():
                # Checks that the lock session is alive before claiming another job.
                lock_conn.execute("SELECT 1")
                job = claim(lock_conn, config)
                if job:
                    active["id"] = job["id"]
                    execute(job, stop, lock_conn)
                    active["id"] = None
                if once:
                    return
                if not job:
                    stop.wait(0.5)
        except WorkerInterrupted:
            pass
        finally:
            stop.set()
            thread.join(timeout=5)
            with store.connect() as conn:
                conn.execute("DELETE FROM worker_state WHERE owner=%s", (owner,))


if __name__ == "__main__":
    run()
