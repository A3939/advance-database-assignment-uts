"""Real session locks and early runner exits; no FP1 or business build is run."""
import json
import os
from pathlib import Path
import time

import pytest

from arsia_ingest import runner
from arsia_ingest.fingerprint import FP1Operation
from arsia_ingest.models import IntakeError
from arsia_ingest.qa_input import write_evidence
from test_manifest import assemble, build
from test_raw_load_postgres import connection


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Real runner lock tests require the isolated PostgreSQL test database and ARSIA_TEST_DSN",
)

# Independent expected key from team contract 04, L4.
KEY = (32113, 2)


@pytest.fixture
def connect(connection):
    import psycopg

    opened = []

    def create():
        conn = psycopg.connect(
            os.environ["ARSIA_TEST_DSN"], autocommit=False, connect_timeout=10,
            options="-c statement_timeout=5000 -c lock_timeout=1000",
            application_name="arsia-b12-test",
        )
        opened.append(conn)
        return conn

    try:
        yield create
    finally:
        for conn in opened:
            conn.close()


def try_lock(conn):
    return conn.execute("SELECT pg_try_advisory_lock(%s,%s)", KEY).fetchone()[0]


def locks(conn):
    return conn.execute("""SELECT pid, classid::bigint, objid::bigint, objsubid, mode, granted
        FROM pg_locks WHERE locktype='advisory'
          AND database=(SELECT oid FROM pg_database WHERE datname=current_database())
          AND classid=%s::oid AND objid=%s::oid AND objsubid=2 ORDER BY pid""", KEY).fetchall()


def counts(conn):
    return {name: conn.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in ("meta.source", "meta.resource", "raw.record")}


def acquire_after_close(conn):
    deadline = time.monotonic() + 5
    while not try_lock(conn):
        if time.monotonic() >= deadline:
            pytest.fail("The session lock remained held after its connection closed")
        time.sleep(0.01)
    return locks(conn)


class ObservedConnection:
    """Record calls while letting the real driver execute every SQL statement."""
    def __init__(self, connection, before_execute=None):
        self.connection = connection
        self.before_execute = before_execute
        self.events = []

    @property
    def autocommit(self):
        return self.connection.autocommit

    def cursor(self):
        return ObservedCursor(self, self.connection.cursor())

    def commit(self):
        self.events.append({"event": "commit"})
        self.connection.commit()

    def rollback(self):
        self.events.append({"event": "rollback"})
        self.connection.rollback()

    def close(self):
        self.events.append({"event": "close"})
        self.connection.close()


class ObservedCursor:
    def __init__(self, observed, cursor):
        self.observed = observed
        self.cursor = cursor

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def execute(self, sql, parameters=None):
        query = " ".join(sql.split())
        if self.observed.before_execute is not None:
            self.observed.before_execute(query)
        self.observed.events.append({"event": "sql", "sql": query, "parameters": parameters})
        self.cursor.execute(sql, parameters)
        return self

    def fetchall(self):
        return self.cursor.fetchall()


@pytest.fixture
def request_args(build, tmp_path, connection):
    calls = []

    def unavailable(*_):
        calls.append("unexpected business call")
        raise AssertionError("This lock test must not execute business modules")

    bindings = {name: runner.ModuleBinding(unavailable, f"sql/{component}.sql", "lock-test-only")
                for name, component in runner.STAGES.items()}
    return {
        "prepared_run": build[0], "manifest": assemble(build),
        "project_root": build[1]["project_root"], "inventory": build[1]["inventory"],
        "modules": runner.BuildModules(**bindings), "evidence_root": tmp_path / "runs",
        "fp1": FP1Operation("b12_not_installed", "fp1", "not-deployed", connection.info.server_version, "sql/fp1.sql"),
    }, calls


def assert_early_exit(observed, result, callbacks):
    assert callbacks == []
    assert observed.connection.closed
    assert observed.events == [
        {"event": "sql", "sql": "SET TRANSACTION ISOLATION LEVEL READ COMMITTED", "parameters": None},
        {"event": "sql", "sql": "SET TIME ZONE 'UTC'", "parameters": None},
        {"event": "sql", "sql": "SET client_encoding TO 'UTF8'", "parameters": None},
        {"event": "sql", "sql": "SELECT pg_try_advisory_lock(%s,%s)", "parameters": KEY},
        {"event": "rollback"}, {"event": "close"},
    ]
    value = result.as_dict()
    assert value["batch_id"] is None
    assert "input_fingerprint" not in value
    directory = Path(value["evidence_ref"])
    assert json.loads((directory / "result.json").read_text()) == value
    assert not list(directory.glob("before-*-commit.json"))
    return value


def test_postgres_session_lock_survives_commit_and_rollback_until_close(connection, connect, tmp_path):
    before = counts(connection)
    owner = connect()
    owner_pid, contender_pid = owner.info.backend_pid, connection.info.backend_pid
    assert owner_pid != contender_pid
    assert try_lock(owner) is True
    checkpoints = []
    for phase in ("acquired", "committed", "rolled_back"):
        if phase != "acquired":
            owner.execute("SELECT 1")
            (owner.commit if phase == "committed" else owner.rollback)()
        assert try_lock(connection) is False
        observed = locks(connection)
        assert observed == [(owner_pid, *KEY, 2, "ExclusiveLock", True)]
        checkpoints.append({"phase": phase, "contender_acquired": False, "pg_locks": observed})
    owner.close()
    released = acquire_after_close(connection)
    assert released == [(contender_pid, *KEY, 2, "ExclusiveLock", True)]
    assert counts(connection) == before
    write_evidence(tmp_path / "lock-check.json", {
        "case": "session_lock_lifecycle", "key": KEY, "owner_pid": owner_pid,
        "contender_pid": contender_pid, "checkpoints": checkpoints, "after_owner_close": released,
        "table_counts_before": before, "table_counts_after": counts(connection),
    })


def test_postgres_busy_runner_does_not_write_or_release_owner_lock(connection, connect, request_args, tmp_path):
    before = counts(connection)
    assert try_lock(connection) is True
    connection.commit()
    owner_pid = connection.info.backend_pid
    observed = ObservedConnection(connect())
    contender_pid = observed.connection.info.backend_pid
    assert owner_pid != contender_pid
    args, callbacks = request_args
    result = runner.run_build(connect=lambda: observed, **args)
    value = assert_early_exit(observed, result, callbacks)
    assert result.exit_code == 2 and value["result"] == "busy"
    held = locks(connection)
    assert held == [(owner_pid, *KEY, 2, "ExclusiveLock", True)]
    assert counts(connection) == before
    write_evidence(tmp_path / "lock-check.json", {
        "case": "runner_busy", "key": KEY, "owner_pid": owner_pid, "contender_pid": contender_pid,
        "runner_result": value, "runner_exit_code": result.exit_code,
        "driver_events": observed.events, "business_calls": callbacks, "owner_lock_after_runner_exit": held,
        "table_counts_before": before, "table_counts_after": counts(connection),
    })


def test_postgres_runner_closes_held_lock_after_pre_history_failure(connection, connect, request_args, tmp_path):
    before = counts(connection)
    checkpoint = {}
    observed = ObservedConnection(connect())
    owner_pid, contender_pid = observed.connection.info.backend_pid, connection.info.backend_pid
    assert owner_pid != contender_pid

    def stop_before_history(query):
        if query.startswith("SELECT batch_id,dataset_kind FROM meta.batch"):
            assert try_lock(connection) is False
            held = locks(connection)
            assert held == [(owner_pid, *KEY, 2, "ExclusiveLock", True)]
            checkpoint.update(contender_acquired=False, pg_locks=held)
            raise IntakeError("B12_TEST_STOP", "Injected stop after acquiring the lock, before reading batch history")

    observed.before_execute = stop_before_history
    args, callbacks = request_args
    result = runner.run_build(connect=lambda: observed, **args)
    value = assert_early_exit(observed, result, callbacks)
    assert checkpoint
    assert result.exit_code == 1 and value["result"] == "failed"
    assert value["stage"] == "history" and value["error_code"] == "B12_TEST_STOP"
    released = acquire_after_close(connection)
    assert released == [(contender_pid, *KEY, 2, "ExclusiveLock", True)]
    assert counts(connection) == before
    write_evidence(tmp_path / "lock-check.json", {
        "case": "runner_pre_history_failure", "key": KEY, "owner_pid": owner_pid,
        "contender_pid": contender_pid, "fault": "Injected Python exception before history SQL; no batch table required",
        "while_runner_held_lock": checkpoint, "runner_result": value, "runner_exit_code": result.exit_code,
        "driver_events": observed.events, "business_calls": callbacks, "after_runner_close": released,
        "table_counts_before": before, "table_counts_after": counts(connection),
    })
