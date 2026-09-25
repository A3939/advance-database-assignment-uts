"""B14 on real PostgreSQL; seeded states are not E publication results."""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from arsia_ingest.recovery import recover_run
from test_manifest import build
from test_recovery import DIGEST, STAMP, add_marker, recovery_case, write_json
from test_runner_postgres import ObservedConnection


pytestmark = pytest.mark.skipif(
    not all(os.environ.get(key) for key in (
        "ARSIA_TEST_DSN", "ARSIA_TEST_ADMIN_DSN", "B14_TEST_RUN",
    )),
    reason="Use tools/verify_b14_postgres.py and its disposable database marker",
)
TABLES = ("meta.batch", "meta.current_release", "dw.dim_month", "qa.check_result")


@pytest.fixture
def database(recovery_case):
    import psycopg
    from psycopg.types.json import Jsonb

    case = recovery_case
    marker_path = case["directory"] / "before-registration-commit.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    write_json(marker_path, {**marker, "input_fingerprint": DIGEST})
    opened = []
    identity = ("arsia", os.environ["B14_TEST_RUN"])

    def open_connection(isolation=None):
        conn = psycopg.connect(
            os.environ["ARSIA_TEST_DSN"], autocommit=False, connect_timeout=10,
            options="-c statement_timeout=5000 -c lock_timeout=500",
            application_name="arsia-b14-recovery-test",
        )
        opened.append(conn)
        if isolation is not None:
            conn.isolation_level = isolation
        return conn

    observer = open_connection()
    assert observer.info.server_version // 10000 == 16
    assert observer.execute(
        "SELECT current_database(),current_setting('arsia.test_run',true)"
    ).fetchone() == identity
    assert observer.execute("SELECT current_user,session_user").fetchone() == (
        "arsia_loader", "arsia_loader",
    )
    assert all(observer.execute("SELECT count(*) FROM " + table).fetchone() == (0,)
               for table in TABLES)
    observer.rollback()

    def register(*, status="running", batch_id=None, manifest=None, digest=DIGEST,
                 kind="synthetic", pointer=False):
        batch_id = batch_id or case["base"]["batch_id"]
        error = {"fixture": "original failure", "code": "B14_TEST"} if status == "failed" else None
        observer.execute(
            """INSERT INTO meta.batch
                (batch_id,dataset_kind,input_fingerprint,manifest,status,finished_at,error_details)
                VALUES (%s,%s,%s,%s,%s,
                    CASE WHEN %s='running' THEN NULL ELSE %s::timestamptz END,%s)""",
            (batch_id, kind, digest, Jsonb(manifest or case["row"][4]), status,
             status, STAMP, Jsonb(error) if error is not None else None),
        )
        if pointer:
            observer.execute(
                "INSERT INTO meta.current_release(dataset_kind,batch_id) VALUES (%s,%s)",
                (kind, batch_id),
            )
        observer.commit()
        return str(batch_id)

    def state():
        return {
            table: observer.execute("SELECT * FROM " + table + " ORDER BY 1").fetchall()
            for table in TABLES
        }

    def recover(*, wrap=None, isolation=None):
        before = {p.name: p.read_bytes() for p in case["directory"].iterdir()}
        original = open_connection(isolation)
        observed = ObservedConnection(original) if wrap is None else wrap(original)
        result = recover_run(connect=lambda: observed, run_dir=case["directory"],
                             evidence_root=case["evidence_root"])
        value = result.as_dict()
        assert original.closed
        assert {p.name: p.read_bytes() for p in case["directory"].iterdir()} == before
        assert json.loads((Path(value["evidence_ref"]) / "result.json").read_text(
            encoding="utf-8")) == value
        assert "fixture-private-driver-error" not in json.dumps(value)
        return value, observed

    try:
        yield SimpleNamespace(open=open_connection, observer=observer, register=register,
                              state=state, recover=recover, case=case)
    finally:
        for conn in opened:
            conn.close()
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"], connect_timeout=10) as admin:
            assert admin.execute(
                "SELECT current_database(),current_setting('arsia.test_run',true)"
            ).fetchone() == identity
            for table in ("qa.check_result", "meta.current_release", "meta.batch", "dw.dim_month"):
                admin.execute("DELETE FROM " + table)
            assert all(admin.execute("SELECT count(*) FROM " + table).fetchone() == (0,)
                       for table in TABLES)
            assert admin.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                                 "AND database=(SELECT oid FROM pg_database WHERE datname='arsia')"
                                 ).fetchone() == (0,)


def writes(observed):
    return [event["sql"] for event in observed.events if event.get("sql", "").startswith(
        ("INSERT", "UPDATE", "DELETE", "TRUNCATE"))]


def test_abandoned_run_closes_once_and_preserves_other_state(database):
    db = database
    target = db.register()
    previous = db.register(batch_id=uuid4(), status="succeeded", pointer=True)
    other = db.register(batch_id=uuid4(), status="running", kind="official")
    db.observer.execute("INSERT INTO dw.dim_month VALUES (202001,2020,1)")
    db.observer.execute("""INSERT INTO qa.check_result
        (batch_id,rule_id,object_key,result,affected_count,actual,expected,evidence)
        VALUES (%s,'B14_TEST','fixture','pass',0,'{}','{}','{}')""", (previous,))
    db.observer.commit()
    before = db.state()
    value, observed = db.recover()
    assert value["resolution"] == "failed" and value["action"] == "closed_abandoned_run"
    assert len(writes(observed)) == 1 and writes(observed)[0].startswith("UPDATE meta.batch")
    assert [e["event"] for e in observed.events].count("commit") == 1
    after = db.state()
    for table in TABLES[1:]:
        assert after[table] == before[table]
    unchanged = lambda rows: [r for r in rows if str(r[0]) in {previous, other}]
    assert unchanged(after["meta.batch"]) == unchanged(before["meta.batch"])
    row = next(r for r in after["meta.batch"] if str(r[0]) == target)
    assert row[4] == "failed" and row[6] is not None
    assert row[7]["error_code"] == "ABANDONED_RUN"
    again, observed = db.recover()
    assert again["resolution"] == "failed" and writes(observed) == []
    assert db.state() == after and again["recovery_id"] != value["recovery_id"]


@pytest.mark.parametrize("pointer", ["target", "newer", "none"])
def test_success_and_replaced_pointer_are_preserved(database, pointer):
    db = database
    db.register(status="succeeded", pointer=pointer == "target")
    if pointer == "newer":
        db.register(batch_id=uuid4(), status="succeeded", pointer=True)
    add_marker(db.case, "publication")
    before = db.state()
    value, observed = db.recover()
    assert value["resolution"] == ("unknown_commit" if pointer == "none" else "succeeded")
    assert db.state() == before and writes(observed) == []
    assert not any(e["event"] == "commit" for e in observed.events)


def test_recorded_failure_keeps_error_and_timestamp(database):
    db = database
    db.register(status="failed")
    before = db.state()
    value, observed = db.recover()
    assert value["resolution"] == "failed" and db.state() == before
    assert writes(observed) == []


@pytest.mark.parametrize("mismatch", ["manifest", "fingerprint", "kind"])
def test_mismatched_identity_refuses_writes(database, mismatch):
    db = database
    args = {}
    if mismatch == "manifest":
        manifest = deepcopy(db.case["row"][4])
        manifest["provenance"]["prepared_by"] = "different fixture run"
        args["manifest"] = manifest
    elif mismatch == "fingerprint":
        args["digest"] = "b" * 64
    else:
        args["kind"] = "official"
    db.register(**args)
    before = db.state()
    value, observed = db.recover()
    assert value["resolution"] == "unknown_commit" and db.state() == before
    assert writes(observed) == []


@pytest.mark.parametrize("phase", ["registration", "publication", "failure"])
def test_missing_registration_is_resolved_only_before_later_stages(database, phase):
    db = database
    if phase != "registration":
        add_marker(db.case, phase)
    value, observed = db.recover()
    assert value["resolution"] == ("not_registered" if phase == "registration" else "unknown_commit")
    assert writes(observed) == [] and all(not rows for rows in db.state().values())


def test_acknowledged_success_cannot_be_reinterpreted_as_abandoned(database):
    db = database
    db.register()
    write_json(db.case["directory"] / "result.json", {
        **db.case["base"], "result": "succeeded", "input_fingerprint": DIGEST,
    })
    before = db.state()
    value, observed = db.recover()
    assert value["resolution"] == "unknown_commit" and db.state() == before
    assert writes(observed) == []


def test_busy_lock_returns_without_state_reads_and_retry_is_fresh(database):
    db = database
    db.register()
    holder = db.open()
    assert holder.execute("SELECT pg_try_advisory_lock(32113,2)").fetchone() == (True,)
    holder.commit()
    before = db.state()
    value, observed = db.recover()
    assert value["resolution"] == "busy" and db.state() == before
    assert not any("FROM meta." in e.get("sql", "") for e in observed.events)
    holder.close()
    again, _ = db.recover()
    assert again["resolution"] == "failed" and again["recovery_id"] != value["recovery_id"]


def test_row_lock_timeout_keeps_state_and_releases_session_lock(database):
    db = database
    target = db.register()
    holder = db.open()
    holder.execute("SELECT batch_id FROM meta.batch WHERE batch_id=%s FOR UPDATE", (target,))
    before = db.state()
    value, observed = db.recover()
    assert value["resolution"] == "unknown_commit" and db.state() == before
    assert writes(observed) == []
    holder.rollback()
    holder.close()
    again, _ = db.recover()
    assert again["resolution"] == "failed"


class LostReply(ObservedConnection):
    """Inject a driver error before/after a real transaction boundary."""
    def __init__(self, connection, *, commit_loss=None, rollback_loss=False):
        super().__init__(connection)
        self.commit_loss = commit_loss
        self.rollback_loss = rollback_loss

    def commit(self):
        self.events.append({"event": "commit"})
        if self.commit_loss == "after":
            self.connection.commit()
        raise ConnectionError("fixture-private-driver-error")

    def rollback(self):
        if not self.rollback_loss:
            return super().rollback()
        self.events.append({"event": "rollback"})
        self.connection.rollback()
        raise ConnectionError("fixture-private-driver-error")


@pytest.mark.parametrize("when", ["before", "after"])
def test_uncertain_recovery_commit_needs_new_connection_and_does_not_retry(database, when):
    db = database
    db.register()
    value, observed = db.recover(wrap=lambda conn: LostReply(conn, commit_loss=when))
    assert value["resolution"] == "unknown_commit"
    assert [e["event"] for e in observed.events].count("commit") == 1
    assert not any(e["event"] == "rollback" for e in observed.events)
    state = db.state()
    assert state["meta.batch"][0][4] == ("running" if when == "before" else "failed")
    again, second = db.recover()
    assert again["resolution"] == "failed" and again["recovery_id"] != value["recovery_id"]
    assert bool(writes(second)) == (when == "before")
    if when == "after":
        assert db.state() == state


def test_uncertain_readonly_rollback_is_unknown_and_retry_preserves_failure(database):
    db = database
    db.register(status="failed")
    before = db.state()
    value, observed = db.recover(wrap=lambda conn: LostReply(conn, rollback_loss=True))
    assert value["resolution"] == "unknown_commit" and writes(observed) == []
    assert db.state() == before
    again, _ = db.recover()
    assert again["resolution"] == "failed" and db.state() == before


def test_driver_repeatable_read_default_is_overridden(database):
    from psycopg import IsolationLevel

    db = database
    db.register()
    levels = []

    def wrap(conn):
        def inspect(query):
            if "FROM meta.batch" in query:
                levels.append(conn.execute("SHOW transaction_isolation").fetchone()[0])
        return ObservedConnection(conn, before_execute=inspect)

    value, _ = db.recover(wrap=wrap, isolation=IsolationLevel.REPEATABLE_READ)
    assert value["resolution"] == "failed" and levels == ["read committed"]


@pytest.mark.parametrize("statement", [
    "DELETE FROM meta.batch WHERE batch_id=%s",
    "UPDATE meta.batch SET input_fingerprint=repeat('b',64) WHERE batch_id=%s",
    "UPDATE meta.batch SET manifest='{}'::jsonb WHERE batch_id=%s",
])
def test_loader_cannot_delete_or_rewrite_immutable_identity(database, statement):
    import psycopg

    db = database
    target = db.register()
    before = db.state()
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.observer.execute(statement, (target,))
    db.observer.rollback()
    assert db.state() == before
    value, _ = db.recover()
    assert value["resolution"] == "failed"


def test_real_foreign_key_blocks_pointing_to_running_batch(database):
    import psycopg

    db = database
    target = db.register()
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.observer.execute("INSERT INTO meta.current_release(dataset_kind,batch_id) "
                            "VALUES ('synthetic',%s)", (target,))
    db.observer.rollback()
    assert db.state()["meta.current_release"] == []
    value, _ = db.recover()
    assert value["resolution"] == "failed"


def test_server_terminated_session_rolls_back_pending_recovery_update(database):
    import psycopg

    db = database
    db.register()

    class TerminatedSession(ObservedConnection):
        def commit(self):
            self.events.append({"event": "commit"})
            with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
                assert admin.execute(
                    "SELECT current_database(),current_setting('arsia.test_run',true)"
                ).fetchone() == ("arsia", os.environ["B14_TEST_RUN"])
                assert admin.execute("SELECT pg_terminate_backend(%s)",
                                     (self.connection.info.backend_pid,)).fetchone() == (True,)
            self.connection.commit()

    before = db.state()
    value, observed = db.recover(wrap=TerminatedSession)
    assert value["resolution"] == "unknown_commit" and db.state() == before
    assert [e["event"] for e in observed.events].count("commit") == 1
    assert not any(e["event"] == "rollback" for e in observed.events)
    again, _ = db.recover()
    assert again["resolution"] == "failed"
