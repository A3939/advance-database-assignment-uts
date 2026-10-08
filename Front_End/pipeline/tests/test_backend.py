"""Real PostgreSQL integration tests in a NEW disposable database per session.

Never truncate the running local laboratory or connect to an existing project DB.
Requires the dedicated regression runner; ordinary pytest never opens a business DB.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb
import pytest

# Check opt-in BEFORE importing any module that binds the runtime singleton.
if not os.environ.get('ARSIA_REGRESSION_INSTANCE') or not os.environ.get('ARSIA_IMPORT_CONFIG'):
    pytest.skip('Database regressions require a new managed instance and explicit runner', allow_module_level=True)

from arsia_pipeline import api, store, worker
from arsia_pipeline.config import CONFIG, ROOT, read_config
from arsia_pipeline.errors import NeedsInput, ValidationFailure


@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    original = read_config()
    expected = os.environ['ARSIA_REGRESSION_INSTANCE']
    assert original['instance_id'] == expected
    assert original.get('test_session_id') and original.get('storage_policy', {}).get('enabled') is True
    assert original.get('dedicated_regression_module') is True
    # Ownership/root validation occurs before connection; connection verifies DB
    # name and persisted instance marker before any test mutation.
    with store.connect(original) as conn:
        assert conn.execute('SELECT count(*) AS n FROM jobs').fetchone()['n'] == 0
    yield original


@pytest.fixture
def client():
    return TestClient(api.app)


def new(client, **options):
    return client.post("/jobs", json=options).json()


def queued(client):
    job = new(client)
    assert client.put(f"/jobs/{job['id']}/files", params={"filename": "test.csv"}, content=b"id,year\na,2024\n").status_code == 200
    assert client.post(f"/jobs/{job['id']}/submit", json={}).status_code == 200
    return job


def claim_specific(job_id):
    cfg = read_config()
    with store.connect() as conn:
        # Other tests can leave queued jobs. Claim only this one deterministically.
        conn.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND id<>%s", (job_id,))
        return worker.claim(conn, cfg)


def result_for(job, source="test_nsw", revision="v1", bad_count=False):
    path = job["work_dir"] / "crashes.jsonl"
    row = {"record_id": "a", "source_id": source, "year": 2024, "month": 1, "severity": "fatal",
           "fatalities": 1, "casualties": 2, "is_fatal_crash": True}
    path.write_text(json.dumps(row) + "\n")
    result = {"source_id": source, "profile_id": "test-v1", "profile_version": "1",
            "fingerprint": hashlib.sha256((source+revision).encode()).hexdigest(),
            "summary": {"crash_count": 2 if bad_count else 1, "fatal_crash_count": 1, "fatalities": 1, "casualties": 2},
            "trend": [], "severity": [], "units": {"status": "unavailable", "rows": []},
            "limitations": ["Synthetic backend test"], "qa": [{"code": "test", "status": "pass", "message": "synthetic"}],
            "files": [], "evidence": {}, "canonical_path": str(path)}

    return seal_loader_fixture(job, result)


def seal_loader_fixture(job, result):
    # Explicit host-QA test double, to exercise the actual DB COPY/reconciliation
    # boundaries. Real parsers and full source QA are tested separately.
    from arsia_pipeline.publication_policy import seal_deterministic
    result['files'] = [{k:f[k] for k in ('id','name','size','sha256')} for f in job['files']]
    seal_deterministic(result, job['files'], native_bundle={'source_id':result['source_id'],'profile_id':result['profile_id']})
    return result


def publish(client, source="test_nsw", revision="v1"):
    job = claim_specific(queued(client)["id"])
    worker.publish(job, result_for(job, source, revision), lambda: None)
    return store.get_job(job["id"])


def test_instance_guard_refuses_unknown_marker(isolated_database):
    with pytest.raises(RuntimeError, match="marker"):
        store.connect({**isolated_database, "instance_id": "wrong"})


def test_initializer_rejects_different_instance(isolated_database):
    with pytest.raises(RuntimeError, match="marker"):
        store.initialize({**isolated_database, "instance_id": "wrong"})


def test_request_id_replay_and_conflict(client):
    key = uuid4().hex
    one = client.post("/jobs", json={"request_id": key, "label": "a"})
    same = client.post("/jobs", json={"request_id": key, "label": "a"})
    assert one.json()["id"] == same.json()["id"]
    assert client.post("/jobs", json={"request_id": key, "label": "changed"}).status_code == 409


def test_upload_hash_and_no_server_path(client):
    job = new(client)
    response = client.put(f"/jobs/{job['id']}/files", params={"filename": "file.csv"}, content=b"id\na\n")
    assert response.status_code == 200
    file = response.json()["files"][0]
    assert file["sha256"] == hashlib.sha256(b"id\na\n").hexdigest()
    assert "path" not in file


@pytest.mark.parametrize("filename", ["../secret.csv", "x\\secret.csv", "x\n.csv", "data.exe"])
def test_upload_filename_guard(client, filename):
    job = new(client)
    assert client.put(f"/jobs/{job['id']}/files", params={"filename": filename}, content=b"x").status_code == 400


def test_unknown_upload_creates_no_directory(client):
    job = uuid4()
    assert client.put(f"/jobs/{job}/files", params={"filename": "x.csv"}, content=b"x").status_code == 404
    assert not (ROOT / "uploads" / str(job)).exists()


def test_size_failure_cleans_partial(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_FILE", 3)
    job = new(client)
    assert client.put(f"/jobs/{job['id']}/files", params={"filename": "x.csv"}, content=b"1234").status_code == 413
    assert not list((ROOT / "uploads" / job["id"]).glob("*"))


def test_global_pending_quota(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_PENDING", 1)
    job = new(client)
    assert client.put(f"/jobs/{job['id']}/files", params={"filename": "x.csv"}, content=b"12").status_code == 413


def test_empty_submission_and_immutable_queued_files(client):
    empty = new(client)
    assert client.post(f"/jobs/{empty['id']}/submit", json={}).status_code == 400
    job = queued(client)
    assert client.put(f"/jobs/{job['id']}/files", params={"filename": "more.csv"}, content=b"x").status_code == 409


def test_real_copy_source_replacement_and_historical_release(client):
    first = publish(client, "alpha")
    second = publish(client, "beta")
    third = publish(client, "alpha", "v2")
    catalog = client.get("/catalog").json()
    mapping = {s["source_id"]: s["batch_id"] for s in catalog["sources"]}
    assert mapping["alpha"] == third["batch_id"] and mapping["beta"] == second["batch_id"]
    old = client.get("/reports", params={"source_id": "alpha", "release_id": first["release_id"]}).json()
    assert old["batch_id"] == first["batch_id"]
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM canonical_crash WHERE batch_id=%s", (third["batch_id"],)).fetchone()["n"] == 1


def test_same_fingerprint_is_no_change(client):
    first = publish(client, "dedup")
    second = publish(client, "dedup")
    assert second["status"] == "no_change"
    assert (first["batch_id"], first["release_id"]) == (second["batch_id"], second["release_id"])
    assert second["result"]["publication_evidence"]["reused_batch_id"] == first["batch_id"]
    assert second["result"]["database_verification"]["status"] == "pass"


def with_units(job, source, eligible=True, generic=False):
    result = result_for(job, source)
    path = job["work_dir"] / "units.jsonl"
    rows = [{"record_id": f"u{i}", "source_id": source, "crash_id": "a", "unit_type": "car", "count_eligible": eligible} for i in range(2)]
    if generic:
        result["profile_id"] = "generic:" + source
        for row in rows:
            row["crash_record_id"] = row.pop("crash_id")
            row.pop("count_eligible")
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result["units_path"] = str(path)
    result["summary"].update(canonical_unit_count=2, unit_count=2 if eligible else None)
    result["units"] = {"status": "available" if eligible else "unavailable", "rows": [{"unit_type": "car", "count": 2}] if eligible else None}
    return seal_loader_fixture(job, result)


@pytest.mark.parametrize("source,eligible,generic", [("units_nsw", True, False), ("units_vic", False, False), ("units_generic", True, True)])
def test_unit_copy_and_eligibility_reconciliation(client, source, eligible, generic):
    job = claim_specific(queued(client)["id"])
    worker.publish(job, with_units(job, source, eligible, generic), lambda: None)
    result = store.get_job(job["id"])["result"]
    assert result["database_verification"]["canonical_unit_count"] == 2
    assert result["database_verification"]["eligible_unit_count"] == (2 if eligible else 0)
    assert result["summary"]["unit_count"] == (2 if eligible else None)


@pytest.mark.parametrize("fault", ["orphan", "duplicate", "wrong_source", "missing_id", "count_mismatch", "restricted_eligible"])
def test_invalid_unit_candidates_roll_back(client, fault):
    source = "unit_fault_" + fault
    job = claim_specific(queued(client)["id"])
    result = with_units(job, source)
    path = Path(result["units_path"])
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if fault == "orphan":
        rows[0]["crash_id"] = "missing"
    elif fault == "duplicate":
        rows[1]["record_id"] = rows[0]["record_id"]
    elif fault == "wrong_source":
        rows[0]["source_id"] = "another_source"
    elif fault == "missing_id":
        rows[0].pop("record_id")
    elif fault == "count_mismatch":
        result["summary"]["canonical_unit_count"] = 3
    elif fault == "restricted_eligible":
        result["units"] = {"status": "unavailable", "rows": None}
        result["summary"]["unit_count"] = None
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    seal_loader_fixture(job, result)
    with pytest.raises(ValidationFailure):
        worker.publish(job, result, lambda: None)
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM batches WHERE source_id=%s", (source,)).fetchone()["n"] == 0


def test_qa_block_keeps_old_release(client):
    before = client.get("/catalog").json()
    job = claim_specific(queued(client)["id"])
    result = result_for(job, "blocked")
    result["qa"] = [{"code": "bad", "status": "block"}]
    with pytest.raises(ValidationFailure):
        worker.publish(job, result, lambda: None)
    assert client.get("/catalog").json() == before


def test_reconciliation_rolls_back_candidate_rows(client):
    before = client.get("/catalog").json()
    job = claim_specific(queued(client)["id"])
    with pytest.raises(ValidationFailure):
        worker.publish(job, result_for(job, "mismatch", bad_count=True), lambda: None)
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM batches WHERE source_id='mismatch'").fetchone()["n"] == 0
    assert client.get("/catalog").json() == before


def test_copy_error_rolls_back_entire_candidate(client):
    before = client.get("/catalog").json()
    job = claim_specific(queued(client)["id"])
    result = result_for(job, "copy_error")
    with Path(result["canonical_path"]).open("a") as handle:
        handle.write('this is not json\n')
    seal_loader_fixture(job, result) # Reach COPY rollback; mutated-output rejection has its own paired test.
    with pytest.raises(json.JSONDecodeError):
        worker.publish(job, result, lambda: None)
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM batches WHERE source_id='copy_error'").fetchone()["n"] == 0
    assert client.get("/catalog").json() == before


def test_cancel_publication_race_keeps_previous_release(client):
    before = client.get("/catalog").json()
    job = claim_specific(queued(client)["id"])
    result = result_for(job, "cancel_race")
    calls = []
    def cancel_after_copy():
        calls.append(1)
        if len(calls) == 2:
            assert client.post(f"/jobs/{job['id']}/cancel").json()["status"] == "cancel_requested"
    with pytest.raises(worker.ImportCancelled):
        worker.publish(job, result, cancel_after_copy)
    assert client.get("/catalog").json() == before
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM batches WHERE source_id='cancel_race'").fetchone()["n"] == 0


def test_published_cannot_cancel(client):
    job = publish(client, "already_done")
    assert client.post(f"/jobs/{job['id']}/cancel").status_code == 409


def test_queue_cancel_and_retry(client):
    job = queued(client)
    assert client.post(f"/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    assert client.post(f"/jobs/{job['id']}/retry", json={}).json()["status"] == "queued"


def test_retry_cannot_bypass_pending_quota(client, monkeypatch):
    job = queued(client)
    assert client.post(f"/jobs/{job['id']}/cancel").json()["status"] == "cancelled"
    monkeypatch.setattr(api, "MAX_PENDING", 1)
    assert client.post(f"/jobs/{job['id']}/retry", json={}).status_code == 413


def test_worker_lock_and_recovery_limit(client):
    job = claim_specific(queued(client)["id"])
    with store.connect() as first, store.connect() as second:
        assert first.execute("SELECT pg_try_advisory_lock(%s) AS yes", (store.LOCK,)).fetchone()["yes"]
        assert not second.execute("SELECT pg_try_advisory_lock(%s) AS yes", (store.LOCK,)).fetchone()["yes"]
        worker.recover_abandoned(first)
        assert store.get_job(job["id"])["status"] == "queued"
        for _ in range(2):
            first.execute("UPDATE jobs SET status='cancelled' WHERE id<>%s AND status='queued'",(job["id"],))
            worker.claim(first,read_config())
            worker.recover_abandoned(first)
            assert store.get_job(job["id"])["status"] == "queued"
        first.execute("UPDATE jobs SET status='cancelled' WHERE id<>%s AND status='queued'",(job["id"],))
        worker.claim(first,read_config())
        worker.recover_abandoned(first)
        assert store.get_job(job["id"])["status"] == "failed"


def test_needs_input_has_durable_attempt_and_retry(client, monkeypatch):
    import arsia_pipeline.processing as processing
    job = claim_specific(queued(client)["id"])
    # Explicit manual profile pauses for missing evidence; automatic unknown
    # sources are exercised separately through the durable Agent tool loop.
    job["options"]["profile"] = {"manual": True}
    def missing(*args, **kwargs):
        raise NeedsInput("Missing counterpart", ["Supply the unit file"])
    monkeypatch.setattr(processing, "process_bundle", missing)
    worker.execute(job, threading.Event())
    assert store.get_job(job["id"])["status"] == "needs_input"
    evidence = client.get(f"/jobs/{job['id']}/evidence").json()
    assert evidence["attempts"][0]["status"] == "needs_input"
    assert "work_dir" not in evidence["attempts"][0]


def test_lost_commit_acknowledgement_queries_committed_success(client, monkeypatch):
    import arsia_pipeline.processing as processing
    job = claim_specific(queued(client)["id"])
    result = result_for(job, "lost_ack")
    monkeypatch.setattr(processing, "process_bundle", lambda *args: result)
    original_publish = worker.publish
    def lost_reply(*args, **kwargs):
        original_publish(*args, **kwargs)
        raise ConnectionError("Synthetic lost reply after actual PostgreSQL commit")
    monkeypatch.setattr(worker, "publish", lost_reply)
    worker.execute(job, threading.Event())
    assert store.get_job(job["id"])["status"] == "succeeded"
    assert client.get("/reports", params={"source_id": "lost_ack"}).status_code == 200


def test_disk_reserve_failure_prevents_processing(client, monkeypatch):
    job = claim_specific(queued(client)["id"])
    from collections import namedtuple
    monkeypatch.setattr(worker.shutil, "disk_usage", lambda _: namedtuple("Usage", "total used free")(100,99,1))
    worker.execute(job, threading.Event())
    assert store.get_job(job["id"])["status"] == "failed"
    assert store.get_job(job["id"])["error"]["code"] == "STORAGE_SPACE"


@pytest.mark.parametrize('closed,status',[(True,4),(False,4)])
def test_worker_loss_of_lock_connection_stops_before_processing(client,monkeypatch,closed,status):
    from types import SimpleNamespace
    import threading
    from arsia_pipeline import processing
    job=claim_specific(queued(client)['id'])
    stopped=threading.Event()
    connection=SimpleNamespace(closed=closed,info=SimpleNamespace(transaction_status=status))
    monkeypatch.setattr(processing,'process_bundle',lambda *a,**k:pytest.fail('Worker without its lock session must not process'))
    with pytest.raises(worker.WorkerInterrupted):
        worker.execute(job,stopped,connection)
    assert stopped.is_set()
    assert store.get_job(job['id'])['status']=='profiling'


def test_manual_retries_and_cancelled_worker_loss_do_not_spend_recovery_budget(client):
    job=claim_specific(queued(client)['id'])
    with store.connect() as conn:
        conn.execute('SELECT pg_advisory_lock(%s)',(store.LOCK,))
        conn.execute("UPDATE attempts SET status='cancelled',finished_at=now() WHERE id=%s",(job['attempt_id'],))
        conn.execute("UPDATE jobs SET status='queued',attempt=12 WHERE id=%s",(job['id'],))
        current=worker.claim(conn,read_config())
        assert current['attempt']==13
        conn.execute("UPDATE jobs SET status='cancel_requested' WHERE id=%s",(job['id'],))
        worker.recover_abandoned(conn)
        cancelled=conn.execute('SELECT error FROM attempts WHERE id=%s',(current['attempt_id'],)).fetchone()['error']
        assert cancelled['automatic_recovery'] is False
        conn.execute("UPDATE jobs SET status='queued' WHERE id=%s",(job['id'],))
        conn.execute("UPDATE jobs SET status='cancelled' WHERE id<>%s AND status='queued'",(job['id'],))
        current=worker.claim(conn,read_config())
        worker.recover_abandoned(conn)
        recovered=conn.execute('SELECT error FROM attempts WHERE id=%s',(current['attempt_id'],)).fetchone()['error']
        assert recovered['automatic_recovery'] is True and recovered['prior_automatic_recoveries']==0
    assert store.get_job(job['id'])['status']=='queued'
