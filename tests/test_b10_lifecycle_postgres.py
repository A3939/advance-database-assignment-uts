"""Runner lifecycle checks in the disposable database; no FP1 or publication."""
from datetime import date
from decimal import Decimal
import hashlib
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from arsia_ingest import runner
from arsia_ingest.models import IntakeError
from test_manifest import build
from test_raw_load_postgres import connection
from test_runner_postgres import ObservedConnection, request_args


pytestmark = pytest.mark.skipif(
    not all(os.environ.get(name) for name in (
        "ARSIA_TEST_DSN", "ARSIA_TEST_ADMIN_DSN", "AC_TEST_RUN",
    )),
    reason="Use the disposable PostgreSQL verifier and its AC_TEST_RUN marker",
)


def batch_row(connection, batch_id):
    return connection.execute(
        """SELECT dataset_kind,status,input_fingerprint,manifest,started_at,
            finished_at,error_details FROM meta.batch WHERE batch_id=%s""",
        (batch_id,),
    ).fetchone()


@pytest.fixture
def database(connection):
    import psycopg
    from psycopg.types.json import Jsonb

    marker = os.environ["AC_TEST_RUN"]
    identity = connection.execute(
        "SELECT current_database(),current_setting('arsia.test_run',true)"
    ).fetchone()
    assert identity == ("arsia", marker)
    assert connection.execute("SELECT current_user,session_user").fetchone() == (
        "arsia_loader", "arsia_loader",
    )
    for table in ("meta.batch", "meta.current_release", "dw.dim_month"):
        assert connection.execute("SELECT count(*) FROM " + table).fetchone() == (0,)
    connection.rollback()
    opened, batches = [], []

    def open_connection(isolation=None):
        conn = psycopg.connect(
            os.environ["ARSIA_TEST_DSN"], autocommit=False, connect_timeout=10,
            options="-c statement_timeout=5000 -c lock_timeout=1000",
            application_name="arsia-b10-lifecycle-test",
        )
        opened.append(conn)
        if isolation is not None:
            conn.isolation_level = isolation
        return conn

    def register(conn, *, kind="synthetic", status="running", batch_id=None):
        batch_id = batch_id or uuid4()
        batches.append(batch_id)
        # This identifies a lifecycle fixture, not an E03 fingerprint or release.
        manifest = {"fixture": "b10-lifecycle", "publication_performed": False}
        digest = hashlib.sha256(("B10 test fixture " + str(batch_id)).encode()).hexdigest()
        error = {"fixture": "original failure"} if status == "failed" else None
        conn.execute(
            """INSERT INTO meta.batch
                (batch_id,dataset_kind,input_fingerprint,manifest,status,finished_at,error_details)
                VALUES (%s,%s,%s,%s,%s,
                    CASE WHEN %s='running' THEN NULL ELSE clock_timestamp() END,%s)""",
            (batch_id, kind, digest, Jsonb(manifest), status, status,
             Jsonb(error) if error is not None else None),
        )
        conn.commit()
        return batch_id

    try:
        yield SimpleNamespace(open=open_connection, register=register)
    finally:
        for conn in opened:
            conn.close()
        connection.rollback()
        # Only the marked test database's administrator removes committed fixtures.
        with psycopg.connect(
            os.environ["ARSIA_TEST_ADMIN_DSN"], connect_timeout=10,
            options="-c statement_timeout=5000 -c lock_timeout=1000",
        ) as admin:
            assert admin.execute(
                "SELECT current_database(),current_setting('arsia.test_run',true)"
            ).fetchone() == identity
            for batch_id in batches:
                admin.execute("DELETE FROM meta.batch WHERE batch_id=%s", (batch_id,))
            for table in ("meta.batch", "meta.current_release", "dw.dim_month"):
                assert admin.execute("SELECT count(*) FROM " + table).fetchone() == (0,)


def test_runner_uses_read_committed_before_history(database, request_args):
    from psycopg import IsolationLevel

    conn = database.open(IsolationLevel.REPEATABLE_READ)
    observed = ObservedConnection(conn)
    checkpoints = {}

    def stop_after_history(query):
        if query.startswith("SELECT batch_id,dataset_kind FROM meta.batch"):
            checkpoints["history_isolation"] = conn.execute(
                "SHOW transaction_isolation"
            ).fetchone()[0]
        elif query.startswith("SELECT cr.batch_id, cr.batch_status"):
            raise IntakeError("B10_TEST_STOP", "Stop after history; no FP1 or business calls")

    observed.before_execute = stop_after_history
    args, callbacks = request_args
    result = runner.run_build(connect=lambda: observed, **args).as_dict()
    assert checkpoints == {"history_isolation": "read committed"}
    assert (result["result"], result["stage"], result["error_code"]) == (
        "failed", "history", "B10_TEST_STOP",
    )
    assert callbacks == [] and conn.closed
    assert not any(event["event"] == "commit" for event in observed.events)
    assert any(event.get("sql", "").startswith(
        "SELECT batch_id,dataset_kind FROM meta.batch"
    ) for event in observed.events)


@pytest.mark.parametrize("kind", ["synthetic", "official"])
def test_running_batch_in_either_mode_blocks_before_fp1(database, request_args, kind):
    from psycopg import IsolationLevel

    writer = database.open()
    batch_id = database.register(writer, kind=kind)
    before = batch_row(writer, batch_id)
    writer.rollback()
    conn = database.open(IsolationLevel.REPEATABLE_READ)
    observed = ObservedConnection(conn)
    args, callbacks = request_args
    result = runner.run_build(connect=lambda: observed, **args).as_dict()
    assert (result["result"], result["stage"], result["error_code"]) == (
        "failed", "history", "RECOVERY_REQUIRED",
    )
    assert result["batch_id"] is None and callbacks == [] and conn.closed
    assert batch_row(writer, batch_id) == before
    assert not any(event["event"] == "commit" for event in observed.events)
    assert not any(event.get("sql", "").startswith(("INSERT", "UPDATE"))
                   for event in observed.events)


@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_read_committed_is_reapplied_after_each_boundary(database, finish):
    from psycopg import IsolationLevel

    reader = database.open(IsolationLevel.REPEATABLE_READ)
    writer = database.open()
    batch_id = uuid4()
    runner._begin_transaction(reader)
    assert reader.execute("SHOW transaction_isolation").fetchone() == ("read committed",)
    assert batch_row(reader, batch_id) is None
    database.register(writer, batch_id=batch_id)
    assert batch_row(reader, batch_id)[1] == "running"
    getattr(reader, finish)()

    # The driver's default remains repeatable read for every new transaction.
    assert reader.isolation_level == IsolationLevel.REPEATABLE_READ
    assert reader.execute("SHOW transaction_isolation").fetchone() == ("repeatable read",)
    reader.rollback()
    runner._begin_transaction(reader)
    assert reader.execute("SHOW transaction_isolation").fetchone() == ("read committed",)
    assert batch_row(reader, batch_id)[1] == "running"
    writer.execute(
        """UPDATE meta.batch SET status='failed',finished_at=clock_timestamp(),
            error_details='{"fixture":"second transaction"}'::jsonb WHERE batch_id=%s""",
        (batch_id,),
    )
    writer.commit()
    assert batch_row(reader, batch_id)[1] == "failed"
    getattr(reader, finish)()


def test_failure_record_needs_caller_commit_and_preserves_history(database):
    from psycopg import IsolationLevel

    writer = database.open(IsolationLevel.REPEATABLE_READ)
    observer = database.open()
    previous = database.register(writer, status="succeeded")
    candidate = database.register(writer)
    before = batch_row(observer, previous)
    observer.rollback()

    runner._begin_transaction(writer)
    writer.execute("INSERT INTO dw.dim_month VALUES (202001,2020,1)")
    writer.rollback()
    runner._begin_transaction(writer)
    error = runner._error(IntakeError(
        "B10_FIXTURE_FAILURE", "Test failure after a rolled-back build write",
        batch_id=candidate, amount=Decimal("1.25"), checked_on=date(2026, 9, 24),
    ), "dw")
    assert json.loads(json.dumps(error)) == error
    runner._mark_failed(writer, str(candidate), "synthetic", error)
    assert batch_row(observer, candidate)[1] == "running"
    assert observer.execute("SELECT count(*) FROM dw.dim_month").fetchone() == (0,)
    writer.commit()

    recorded = batch_row(observer, candidate)
    assert recorded[1] == "failed" and recorded[5] is not None
    assert recorded[6] == error
    assert batch_row(observer, previous) == before
    assert observer.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    assert observer.execute("SELECT count(*) FROM dw.dim_month").fetchone() == (0,)


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_failure_record_rejects_finished_batches(database, status):
    writer = database.open()
    observer = database.open()
    batch_id = database.register(writer, status=status)
    before = batch_row(observer, batch_id)
    observer.rollback()
    runner._begin_transaction(writer)
    with pytest.raises(IntakeError) as error:
        runner._mark_failed(writer, str(batch_id), "synthetic", {"fixture": "must not overwrite"})
    assert error.value.code == "FAILURE_STATE"
    writer.rollback()
    assert batch_row(observer, batch_id) == before
