"""B14 recovery using real S0 manifests and scripted SQL, not PostgreSQL."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
from types import ModuleType
from uuid import UUID, uuid4

import pytest

from arsia_ingest.models import IntakeError
from arsia_ingest.recovery import main, recover_run
from test_manifest import assemble, build
from test_runner import DIGEST, execute, setup


STAMP = "2026-09-21T00:00:00+00:00"
FINISHED = datetime.fromisoformat(STAMP)


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


class RecoveryConnection:
    autocommit = False

    def __init__(self, row=None, pointers=()):
        self.row = deepcopy(row)
        self.durable = deepcopy(row)
        self.pointers = deepcopy(list(pointers))
        self.calls = []
        self.events = []
        self.lock_reply = [(True,)]
        self.query_error = None
        self.rollback_error = False
        self.close_error = False
        self.commit_loss = None
        self.update_reply = None

    def cursor(self):
        return RecoveryCursor(self)

    def commit(self):
        self.events.append("commit")
        if self.commit_loss is not False:
            self.durable = deepcopy(self.row)
        if self.commit_loss is not None:
            raise ConnectionError("private connection details must not reach evidence")

    def rollback(self):
        self.events.append("rollback")
        if self.rollback_error:
            raise ConnectionError("private rollback details")
        self.row = deepcopy(self.durable)

    def close(self):
        self.events.append("close")
        self.row = deepcopy(self.durable)
        if self.close_error:
            raise ConnectionError("private close details")


class RecoveryCursor:
    def __init__(self, db):
        self.db = db
        self.reply = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, parameters=None):
        query = " ".join(sql.split())
        db = self.db
        db.calls.append((query, parameters))
        self.reply = []
        if query.startswith("SET "):
            db.events.append(query)
        elif "pg_try_advisory_lock" in query:
            assert parameters == (32113, 2)
            db.events.append("lock")
            self.reply = db.lock_reply
        elif "FROM meta.current_release" in query:
            db.events.append("pointer")
            assert "LEFT JOIN meta.batch" in query
            assert "cr.dataset_kind=%s OR cr.batch_id=%s" in query
            assert parameters[0] == "synthetic"
            UUID(str(parameters[1]))
            self.reply = db.pointers
        elif "FROM meta.batch" in query:
            db.events.append("batch")
            assert "WHERE batch_id=%s::uuid FOR UPDATE" in query
            assert len(parameters) == 1
            self.reply = [] if db.row is None else [db.row]
        elif query.startswith("UPDATE meta.batch SET status='failed'"):
            db.events.append("update")
            assert "AND status='running'" in query
            assert "finished_at IS NULL" in query
            assert "input_fingerprint=%s" in query and "manifest=%s::jsonb" in query
            error, batch_id, kind, digest, manifest = parameters
            assert db.row is not None and db.row[2] == "running"
            assert (batch_id, kind, digest, json.loads(manifest)) == (str(db.row[0]), db.row[1], db.row[3], db.row[4])
            changed = list(db.row)
            changed[2], changed[5], changed[6] = "failed", FINISHED, json.loads(error)
            db.row = tuple(changed)
            self.reply = [(batch_id,)] if db.update_reply is None else db.update_reply
        else:
            pytest.fail(f"Unexpected recovery SQL: {query}")
        if db.events[-1] == db.query_error:
            raise ConnectionError("private query connection details")
        self.rowcount = len(self.reply)
        return self

    def fetchall(self):
        return deepcopy(self.reply)

    def fetchone(self):
        return deepcopy(self.reply[0]) if self.reply else None


@pytest.fixture
def recovery_case(build, tmp_path):
    frozen = assemble(build)
    run_id, batch_id = str(uuid4()), str(uuid4())
    directory = tmp_path / "old-evidence" / "synthetic" / "runs" / run_id
    directory.mkdir(parents=True)
    base = {"run_id": run_id, "batch_id": batch_id, "dataset_kind": "synthetic", "evidence_ref": str(directory)}
    write_json(directory / "manifest.json", frozen.as_dict())
    write_json(directory / "before-registration-commit.json", {**base, "stage": "registration", "checked_at": STAMP})
    row = (UUID(batch_id), "synthetic", "running", DIGEST, frozen.as_dict(), None, None)
    return {"directory": directory, "base": base, "row": row, "evidence_root": tmp_path / "recovery-evidence"}


def recover(case, db):
    db.events.append("connect")
    result = recover_run(connect=lambda: db, run_dir=case["directory"], evidence_root=case["evidence_root"])
    value = result.as_dict()
    assert value["run_id"] == case["base"]["run_id"]
    assert value["batch_id"] == case["base"]["batch_id"]
    assert value["dataset_kind"] == "synthetic"
    assert "qa_summary" not in value and "result" not in value
    recovery_id = str(UUID(value["recovery_id"]))
    evidence = Path(value["evidence_ref"])
    assert evidence == case["evidence_root"] / "synthetic" / "recoveries" / recovery_id
    assert evidence.is_dir() and evidence != case["directory"]
    assert json.loads((evidence / "result.json").read_text()) == value
    assert "private " not in json.dumps(value)
    assert db.events[-1] == "close"
    return result, value


def changed_row(case, **changes):
    names = ("batch_id", "kind", "status", "digest", "manifest", "finished_at", "error")
    fields = dict(zip(names, case["row"])) | changes
    return tuple(fields[name] for name in names)


def add_marker(case, stage):
    write_json(case["directory"] / f"before-{stage}-commit.json", {**case["base"], "stage": stage, "checked_at": STAMP})


def successful_pointer(case):
    return [("synthetic", case["base"]["batch_id"], "succeeded", "synthetic", "succeeded")]


def test_running_recovery_is_guarded_and_keeps_original_receipts(recovery_case):
    case = recovery_case
    before = {p.name: p.read_bytes() for p in case["directory"].iterdir()}
    db = RecoveryConnection(case["row"])
    result, value = recover(case, db)
    assert result.exit_code == 0 and value["resolution"] == "failed"
    assert db.events.count("commit") == db.events.count("update") == 1
    assert db.events.index("lock") < db.events.index("batch") < db.events.index("update") < db.events.index("commit")
    assert "SET TRANSACTION ISOLATION LEVEL READ COMMITTED" in db.events
    assert db.events.index("SET TRANSACTION ISOLATION LEVEL READ COMMITTED") < db.events.index("lock")
    assert db.durable[2] == "failed" and db.durable[5] is not None
    assert db.durable[6] and db.durable[6]["checked_at"]
    assert {p.name: p.read_bytes() for p in case["directory"].iterdir()} == before
    assert all(not sql.startswith(("INSERT", "DELETE")) and "UPDATE meta.current_release" not in sql for sql, _ in db.calls)
    second = RecoveryConnection(db.durable)
    second_result, second_value = recover(case, second)
    assert second_result.exit_code == 0 and second_value["resolution"] == "failed"
    assert second_value["recovery_id"] != value["recovery_id"]
    assert second.durable == db.durable and "update" not in second.events and "commit" not in second.events


@pytest.mark.parametrize("pointer", ["target", "replaced", "none"])
def test_success_is_preserved_and_resolution_requires_a_current_pointer(recovery_case, pointer):
    case = recovery_case
    batch_id = case["base"]["batch_id"]
    pointer_id = batch_id if pointer == "target" else str(uuid4())
    pointers = [] if pointer == "none" else [("synthetic", pointer_id, "succeeded", "synthetic", "succeeded")]
    db = RecoveryConnection(changed_row(case, status="succeeded", finished_at=FINISHED), pointers)
    before = deepcopy(db.durable)
    result, value = recover(case, db)
    assert result.exit_code == (3 if pointer == "none" else 0)
    assert value["resolution"] == ("unknown_commit" if pointer == "none" else "succeeded")
    assert db.durable == before and "update" not in db.events and "commit" not in db.events


def test_existing_failure_preserves_its_error_and_timestamp(recovery_case):
    case = recovery_case
    error = {"stage": "vault", "error_code": "ORIGINAL", "checked_at": STAMP, "details": {"row_locator": "csv:2"}}
    db = RecoveryConnection(changed_row(case, status="failed", finished_at=FINISHED, error=error))
    result, value = recover(case, db)
    assert result.exit_code == 0 and value["resolution"] == "failed"
    assert db.durable[5:] == (FINISHED, error)
    assert "update" not in db.events and "commit" not in db.events


def test_busy_does_not_read_or_change_database_state(recovery_case):
    db = RecoveryConnection(recovery_case["row"])
    db.lock_reply = [(False,)]
    result, value = recover(recovery_case, db)
    assert result.exit_code == 2 and value["resolution"] == "busy"
    assert db.events[-2:] == ["rollback", "close"]
    assert not {"batch", "pointer", "update", "commit"}.intersection(db.events)


@pytest.mark.parametrize("stage", [None, "registration", "publication", "failure", "finished_success", "finished_failure"])
def test_missing_batch_is_not_automatically_an_uncommitted_registration(recovery_case, stage):
    case = recovery_case
    if stage in ("publication", "failure"):
        add_marker(case, stage)
    if stage == "registration":
        write_json(case["directory"] / "result.json", {**case["base"], "result": "unknown_commit", "diagnostics": [{"stage": "registration"}]})
    if stage in ("finished_success", "finished_failure"):
        add_marker(case, "publication" if stage == "finished_success" else "failure")
        write_json(case["directory"] / "result.json", {**case["base"], "result": "succeeded" if stage == "finished_success" else "failed", "input_fingerprint": DIGEST})
    db = RecoveryConnection()
    result, value = recover(case, db)
    expected = "not_registered" if stage in (None, "registration") else "unknown_commit"
    assert value["resolution"] == expected and result.exit_code == (0 if expected == "not_registered" else 3)
    assert "update" not in db.events and "commit" not in db.events


@pytest.mark.parametrize("diagnostics,expected", [
    ([{"stage": "registration"}, {"stage": "close"}, {"stage": "result_evidence"}], "not_registered"),
    ([{"stage": "registration"}, {"stage": "publication"}], "unknown_commit"),
    ([{"stage": "registration"}, {"stage": "failure_commit"}], "unknown_commit"),
    ([{"stage": "registration"}, {"stage": "registration"}], "unknown_commit"),
    ([{"stage": "close"}], "unknown_commit"),
    ([{"stage": "registration"}, "malformed"], "unknown_commit"),
    ({"stage": "registration"}, "unknown_commit"),
])
def test_absent_registration_requires_unambiguous_commit_diagnostics(recovery_case, diagnostics, expected):
    case = recovery_case
    write_json(case["directory"] / "result.json", {**case["base"], "result": "unknown_commit", "diagnostics": diagnostics})
    db = RecoveryConnection()
    result, value = recover(case, db)
    assert value["resolution"] == expected and result.exit_code == (0 if expected == "not_registered" else 3)
    assert "update" not in db.events and "commit" not in db.events


@pytest.mark.parametrize("case_name", ["batch_id", "mode", "manifest", "manifest_type", "digest", "running_finished", "succeeded_unfinished", "failed_no_error", "unexpected_status"])
def test_ambiguous_or_mismatched_row_never_changes_history(recovery_case, case_name):
    case = recovery_case
    changes = {
        "batch_id": {"batch_id": uuid4()}, "mode": {"kind": "official"},
        "digest": {"digest": "not-fp1"}, "running_finished": {"finished_at": FINISHED},
        "succeeded_unfinished": {"status": "succeeded"},
        "failed_no_error": {"status": "failed", "finished_at": FINISHED},
        "unexpected_status": {"status": "unknown_commit"},
    }
    if case_name.startswith("manifest"):
        value = deepcopy(case["row"][4])
        value["files"][0]["raw_count"] = float(value["files"][0]["raw_count"]) if case_name == "manifest_type" else 999
        changes[case_name] = {"manifest": value}
    db = RecoveryConnection(changed_row(case, **changes[case_name]))
    original = deepcopy(db.durable)
    result, value = recover(case, db)
    assert result.exit_code == 3 and value["resolution"] == "unknown_commit"
    assert "update" not in db.events and "commit" not in db.events and db.durable == original


def test_original_fingerprint_is_checked_when_it_was_recorded(recovery_case):
    case = recovery_case
    add_marker(case, "publication")
    write_json(case["directory"] / "result.json", {**case["base"], "result": "succeeded", "input_fingerprint": "b2" * 32})
    db = RecoveryConnection(changed_row(case, status="succeeded", finished_at=FINISHED), successful_pointer(case))
    result, value = recover(case, db)
    assert result.exit_code == 3 and value["resolution"] == "unknown_commit"
    assert "update" not in db.events and "commit" not in db.events


def test_acknowledged_success_cannot_be_relabelled_failed(recovery_case):
    case = recovery_case
    add_marker(case, "publication")
    write_json(case["directory"] / "result.json", {**case["base"], "result": "succeeded", "input_fingerprint": DIGEST})
    db = RecoveryConnection(case["row"])
    result, value = recover(case, db)
    assert result.exit_code == 3 and value["resolution"] == "unknown_commit"
    assert "update" not in db.events and "commit" not in db.events


def test_recovery_uses_saved_manifest_without_rehashing_current_code(recovery_case, build):
    case = recovery_case
    project_root = build[1]["project_root"]
    for path in project_root.rglob("*.sql"):
        path.unlink()
    db = RecoveryConnection(changed_row(case, status="succeeded", finished_at=FINISHED), successful_pointer(case))
    result, value = recover(case, db)
    assert result.exit_code == 0 and value["resolution"] == "succeeded"
    assert not any("pg_proc" in sql or "fp1" in sql for sql, _ in db.calls)


def test_changed_receipt_after_connect_blocks_recovery(recovery_case):
    case = recovery_case
    db = RecoveryConnection(case["row"])

    def connect():
        marker = case["directory"] / "before-registration-commit.json"
        marker.write_text(marker.read_text() + "\n")
        return db

    result = recover_run(connect=connect, run_dir=case["directory"], evidence_root=case["evidence_root"])
    assert result.exit_code == 3 and result.as_dict()["resolution"] == "unknown_commit"
    assert "update" not in db.events and "commit" not in db.events
    assert db.events[-2:] == ["rollback", "close"]


@pytest.mark.parametrize("state", ["succeeded", "absent"])
def test_receipt_changed_during_query_blocks_read_only_resolution(recovery_case, monkeypatch, state):
    case = recovery_case
    row = changed_row(case, status="succeeded", finished_at=FINISHED) if state == "succeeded" else None
    pointers = successful_pointer(case) if state == "succeeded" else []
    db = RecoveryConnection(row, pointers)
    execute_query = RecoveryCursor.execute

    def change_after_query(cursor, sql, parameters=None):
        reply = execute_query(cursor, sql, parameters)
        if "FROM meta.current_release" in sql:
            marker = case["directory"] / "before-registration-commit.json"
            marker.write_text(marker.read_text() + "\n")
        return reply

    monkeypatch.setattr(RecoveryCursor, "execute", change_after_query)
    result, value = recover(case, db)
    assert result.exit_code == 3 and value["resolution"] == "unknown_commit"
    assert "update" not in db.events and "commit" not in db.events
    assert db.events[-2:] == ["rollback", "close"]


@pytest.mark.parametrize("state", ["succeeded", "absent"])
def test_read_only_resolution_requires_successful_rollback(recovery_case, state):
    row = changed_row(recovery_case, status="succeeded", finished_at=FINISHED) if state == "succeeded" else None
    pointers = successful_pointer(recovery_case) if state == "succeeded" else []
    db = RecoveryConnection(row, pointers)
    db.rollback_error = True
    result, value = recover(recovery_case, db)
    assert result.exit_code == 3 and value["resolution"] == "unknown_commit"
    assert "update" not in db.events and "commit" not in db.events
    assert db.events.count("rollback") == 2


def test_close_failure_after_acknowledged_recovery_commit_keeps_resolution(recovery_case):
    db = RecoveryConnection(recovery_case["row"])
    db.close_error = True
    result, value = recover(recovery_case, db)
    assert result.exit_code == 0 and value["resolution"] == "failed"
    assert db.durable[2] == "failed" and db.events.count("commit") == 1
    assert value["diagnostics"] and "private " not in json.dumps(value)


@pytest.mark.parametrize("case_name", ["running_target", "wrong_mode", "wrong_join", "missing_join", "duplicate"])
def test_inconsistent_current_pointer_blocks_recovery(recovery_case, case_name):
    case = recovery_case
    batch_id = case["base"]["batch_id"]
    normal = ("synthetic", str(uuid4()), "succeeded", "synthetic", "succeeded")
    pointers = {
        "running_target": [("synthetic", batch_id, "succeeded", "synthetic", "running")],
        "wrong_mode": [("official", batch_id, "succeeded", "synthetic", "succeeded")],
        "wrong_join": [("synthetic", str(uuid4()), "succeeded", "official", "succeeded")],
        "missing_join": [("synthetic", str(uuid4()), "succeeded", None, None)],
        "duplicate": [normal, normal],
    }[case_name]
    db = RecoveryConnection(case["row"], pointers)
    result, value = recover(case, db)
    assert result.exit_code == 3 and value["resolution"] == "unknown_commit"
    assert "update" not in db.events and "commit" not in db.events


@pytest.mark.parametrize("fault", ["batch", "pointer", "update", "update_empty", "update_other", "rollback", "lock_shape", "autocommit"])
def test_database_failures_remain_unknown_and_close_connection(recovery_case, fault):
    db = RecoveryConnection(recovery_case["row"])
    if fault in ("batch", "pointer", "update"):
        db.query_error = fault
    elif fault == "update_empty":
        db.update_reply = []
    elif fault == "update_other":
        db.update_reply = [(str(uuid4()),)]
    elif fault == "rollback":
        db.query_error = "batch"
        db.rollback_error = True
    elif fault == "lock_shape":
        db.lock_reply = [(None,)]
    else:
        db.autocommit = True
    result, value = recover(recovery_case, db)
    assert result.exit_code == 3 and value["resolution"] == "unknown_commit"
    assert "commit" not in db.events and db.durable[2] == "running"


@pytest.mark.parametrize("committed", [False, True])
def test_lost_recovery_commit_does_not_retry_or_guess(recovery_case, committed):
    db = RecoveryConnection(recovery_case["row"])
    db.commit_loss = committed
    result, value = recover(recovery_case, db)
    assert result.exit_code == 3 and value["resolution"] == "unknown_commit"
    assert db.events.count("commit") == db.events.count("update") == 1
    assert db.events[db.events.index("commit") + 1:] == ["close"]
    fresh = RecoveryConnection(db.durable)
    retry, resolved = recover(recovery_case, fresh)
    assert retry.exit_code == 0 and resolved["resolution"] == "failed"
    assert fresh.events.count("update") == (0 if committed else 1)


@pytest.mark.parametrize("fault", ["missing_manifest", "missing_marker", "wrong_run", "wrong_batch", "wrong_mode", "wrong_stage", "non_utc", "both_later_markers", "bad_json"])
def test_invalid_receipts_stop_before_connect(recovery_case, fault):
    case = recovery_case
    marker = case["directory"] / "before-registration-commit.json"
    if fault == "missing_manifest":
        (case["directory"] / "manifest.json").unlink()
    elif fault == "missing_marker":
        marker.unlink()
    elif fault == "both_later_markers":
        add_marker(case, "publication")
        add_marker(case, "failure")
    elif fault == "bad_json":
        marker.write_text("{")
    else:
        value = json.loads(marker.read_text())
        key, replacement = {
            "wrong_run": ("run_id", str(uuid4())),
            "wrong_batch": ("batch_id", "not-a-uuid"),
            "wrong_mode": ("dataset_kind", "official"),
            "wrong_stage": ("stage", "publication"),
            "non_utc": ("checked_at", "2026-09-21T10:00:00+10:00"),
        }[fault]
        value[key] = replacement
        write_json(marker, value)
    called = []
    with pytest.raises(IntakeError):
        recover_run(connect=lambda: called.append(True), run_dir=case["directory"], evidence_root=case["evidence_root"])
    assert called == []


@pytest.mark.parametrize("phase", ["registration", "publication", "failure"])
@pytest.mark.parametrize("committed", [False, True])
def test_recovers_actual_runner_receipts_after_lost_commit(setup, tmp_path, phase, committed):
    original, _ = setup
    original.loss_phase, original.loss_committed = phase, committed
    if phase == "failure":
        original.fail_stage = "vault"
    _, outcome, value = execute(setup)
    assert outcome.exit_code == 3
    directory = Path(value["evidence_ref"])
    before = {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
    batch_id = value["batch_id"]
    stored = original.durable["batches"].get(batch_id)
    row = None if stored is None else (
        UUID(batch_id), stored["kind"], stored["status"], stored["digest"], stored["manifest"],
        FINISHED if stored["status"] != "running" else None, stored.get("error"),
    )
    pointers = [(kind, bid, "succeeded", original.durable["batches"][bid]["kind"], original.durable["batches"][bid]["status"])
                for kind, bid in original.durable["current"].items()]
    db = RecoveryConnection(row, pointers)
    case = {"directory": directory, "base": value, "evidence_root": tmp_path / "recovered"}
    result, resolved = recover(case, db)
    expected = "not_registered" if phase == "registration" and not committed else "succeeded" if phase == "publication" and committed else "failed"
    assert result.exit_code == 0 and resolved["resolution"] == expected
    needs_update = row is not None and row[2] == "running"
    assert db.events.count("update") == db.events.count("commit") == int(needs_update)
    assert {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()} == before


def cli_arguments(case, monkeypatch, factory):
    module = ModuleType("arsia_recovery_cli_test")
    module.connect = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return ["--connect", f"{module.__name__}:connect", "--run-dir", str(case["directory"]),
            "--evidence-root", str(case["evidence_root"])]


def test_cli_reports_a_resolved_failed_batch_as_exit_zero(recovery_case, monkeypatch, capsys):
    case = recovery_case
    db = RecoveryConnection(changed_row(case, status="failed", finished_at=FINISHED,
                                       error={"error_code": "ORIGINAL", "checked_at": STAMP}))
    code = main(cli_arguments(case, monkeypatch, lambda: db))
    output = capsys.readouterr().out
    value = json.loads(output)
    assert code == 0 and value["resolution"] == "failed"
    assert value["batch_id"] == case["base"]["batch_id"]
    assert "private " not in output and "qa_summary" not in value
    assert "update" not in db.events and "commit" not in db.events
    assert db.events[-2:] == ["rollback", "close"]


def test_cli_connection_failure_returns_unknown_without_connection_details(recovery_case, monkeypatch, capsys):
    def unavailable():
        raise ConnectionError("private connection details must not reach CLI output")

    code = main(cli_arguments(recovery_case, monkeypatch, unavailable))
    output = capsys.readouterr().out
    value = json.loads(output)
    assert code == 3 and value["resolution"] == "unknown_commit"
    assert value["diagnostics"][0]["stage"] == "connect"
    assert "ConnectionError" in value["diagnostics"][0]["message"]
    assert "private " not in output
