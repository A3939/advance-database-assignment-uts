"""Runner control flow with S0 archives and scripted SQL; no PostgreSQL is run."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from arsia_ingest import runner
from arsia_ingest.fingerprint import FP1Operation
from arsia_ingest.manifest import REQUIRED_CHECKS
from arsia_ingest.models import IntakeError
from test_manifest import assemble, build


DIGEST = "a1" * 32


class ScriptedConnection:
    autocommit = False

    def __init__(self):
        self.state = {name: {} for name in ("sources", "resources", "raw", "batches", "current", "qa")}
        self.state["layers"] = []
        self.durable = deepcopy(self.state)
        self.events = []
        self.calls = []
        self.callbacks = []
        self.busy = False
        self.stale = []
        self.digest = DIGEST
        self.phase = None
        self.loss_phase = None
        self.loss_committed = False
        self.close_error = False
        self.rollback_error = False
        self.noop_publish = False
        self.publish_then_raise = False
        self.fail_stage = None
        self.corrupt_raw = False
        self.current_override = None
        self.summary_override = None
        self.closed = False

    def cursor(self):
        return ScriptedCursor(self)

    def commit(self):
        self.events.append(f"commit:{self.phase}")
        if self.phase == self.loss_phase:
            if self.loss_committed:
                self.durable = deepcopy(self.state)
            raise ConnectionError("simulated lost COMMIT response")
        self.durable = deepcopy(self.state)

    def rollback(self):
        self.events.append("rollback")
        if self.rollback_error:
            raise ConnectionError("simulated lost connection")
        self.state = deepcopy(self.durable)

    def close(self):
        self.events.append("close")
        self.closed = True
        self.state = deepcopy(self.durable)
        if self.close_error:
            raise ConnectionError("simulated close error")


class ScriptedCursor:
    def __init__(self, connection):
        self.connection = connection
        self.reply = []
        self.rowcount = 0
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, parameters=None):
        db = self.connection
        query = " ".join(sql.split())
        db.calls.append((query, parameters))
        self.reply = []
        state = db.state
        if query.startswith("SET "):
            db.events.append(query)
        elif "pg_try_advisory_lock" in query:
            assert parameters == (32113, 2)
            db.events.append("lock")
            self.reply = [(not db.busy,)]
        elif query.startswith("SELECT batch_id,dataset_kind FROM meta.batch"):
            db.events.append("stale")
            assert parameters is None and "WHERE status='running'" in query
            self.reply = db.stale
        elif "FROM meta.current_release" in query:
            db.events.append("current")
            kind, = parameters
            if db.current_override is not None:
                self.reply = db.current_override
            elif kind in state["current"]:
                batch_id = state["current"][kind]
                batch = state["batches"][batch_id]
                self.reply = [(batch_id, "succeeded", batch["kind"], batch["status"], batch["digest"], batch["manifest"])]
        elif "current_setting('server_version_num')" in query:
            self.reply = [("160004", "UTF8", "UTF8", "UTC")]
        elif "FROM pg_catalog.pg_proc" in query:
            assert parameters == ("test_binding", "fp1")
            self.reply = [(True,)]
        elif query == 'SELECT "test_binding"."fp1"(%s::jsonb)':
            db.events.append("fp1")
            value = json.loads(parameters[0])
            assert "provenance" not in value
            self.reply = [(db.digest,)]
        elif query.startswith("INSERT INTO meta.source"):
            db.events.append("source")
            state["sources"].setdefault(parameters[0], parameters)
        elif query.startswith("SELECT source_id, jurisdiction_code"):
            self.reply = [state["sources"][parameters[0]]]
        elif query.startswith("INSERT INTO meta.resource"):
            state["resources"].setdefault(parameters[0], parameters)
        elif query.startswith("SELECT resource_id, source_id, resource_role"):
            self.reply = [state["resources"][parameters[0]]]
        elif query.startswith("INSERT INTO raw.record"):
            db.events.append("raw_insert")
            raw_id, resource, source, digest, parser, locator, payload = parameters
            key = (resource, digest, parser, locator)
            if key not in state["raw"]:
                state["raw"][key] = (raw_id, source, resource, digest, parser, locator, json.loads(payload))
                self.reply = [(raw_id,)]
        elif query.startswith("SELECT raw_record_id, source_id, payload ="):
            payload, *key = parameters
            row = state["raw"][tuple(key)]
            self.reply = [(row[0], row[1], row[6] == json.loads(payload))]
        elif query.startswith("SELECT raw_record_id, source_id, resource_id"):
            db.events.append("qa02")
            resource, digest, parser, last_id, repeated = parameters
            assert last_id == repeated and "LIMIT 1000" in query
            self.reply = sorted(
                (row for key, row in state["raw"].items() if key[:3] == (resource, digest, parser)
                 and (last_id is None or UUID(row[0]).int > UUID(last_id).int)),
                key=lambda row: UUID(row[0]).int,
            )[:1000]
        elif query.startswith("INSERT INTO meta.batch"):
            db.events.append("batch_insert")
            batch_id, kind, digest, value = parameters
            UUID(batch_id)
            assert batch_id not in state["batches"]
            state["batches"][batch_id] = {"kind": kind, "digest": digest, "manifest": json.loads(value), "status": "running"}
            db.phase = "registration"
            self.reply = [(batch_id,)]
        elif query.startswith("INSERT INTO qa.check_result"):
            batch_id, rule, object_key, result, affected, actual, expected, evidence, raw_id, checked = parameters
            assert state["batches"][batch_id]["status"] == "running"
            key = (batch_id, rule, object_key)
            assert key not in state["qa"]
            state["qa"][key] = (result, affected, json.loads(actual), json.loads(expected), json.loads(evidence))
            db.events.append("qa_write:" + rule)
        elif query.startswith("SELECT rule_id,result,affected_count"):
            db.events.append("summary")
            batch_id, = parameters
            self.reply = db.summary_override if db.summary_override is not None else [
                (rule, value[0], value[1]) for (bid, rule, obj), value in sorted(state["qa"].items())
                if bid == batch_id and obj == "batch"
            ]
        elif query.startswith("UPDATE meta.batch SET status='failed'"):
            db.events.append("failure_update")
            error, batch_id, kind = parameters
            assert "AND status='running'" in query
            batch = state["batches"].get(batch_id)
            if batch is not None and batch["kind"] == kind and batch["status"] == "running":
                batch.update(status="failed", error=json.loads(error))
                db.phase = "failure"
                self.reply = [(batch_id,)]
        elif query == "SELECT %s::text":
            self.reply = [(parameters[0],)]
        else:
            pytest.fail(f"Unexpected runner SQL: {query}")
        self.rowcount = len(self.reply)
        return self

    def fetchall(self):
        return list(self.reply)

    def fetchone(self):
        return self.reply[0] if self.reply else None

    def fetchmany(self, size):
        assert size == 1000
        return self.reply[:size]


def summaries():
    return [(rule, "limited" if rule == "QA07_LOCATION" else "pass", 2 if rule == "QA07_LOCATION" else 0)
            for rule in REQUIRED_CHECKS]


@pytest.fixture
def setup(build, tmp_path):
    frozen = assemble(build)
    db = ScriptedConnection()
    callbacks = {}

    def callback(name):
        def module(shared, context):
            db.events.append("module:" + name)
            db.callbacks.append((name, shared, context))
            assert isinstance(shared, runner.ModuleConnection)
            assert context.manifest.as_dict() == frozen.as_dict()
            assert context.dataset_kind == "synthetic"
            assert context.evidence.directory.name == name
            for attribute in ("commit", "rollback", "close"):
                assert not hasattr(shared, attribute)
            with shared.cursor() as cursor:
                assert not hasattr(cursor, "connection")
                assert cursor.execute("SELECT %s::text", (name,)).fetchone() == (name,)
            if name == db.fail_stage:
                raise IntakeError("TEST_STAGE", "test stage failure", rule_id="TEST", row_locator="csv:1")
            db.state["layers"].append(name)
            if name == "dw" and db.corrupt_raw:
                key = next(iter(db.state["raw"]))
                row = db.state["raw"][key]
                changed = dict(row[-1])
                changed[next(iter(changed))] = "changed in test"
                db.state["raw"][key] = (*row[:-1], changed)
            if name == "qa_c":
                # Test-only external QA replies; these do not exercise C/D's checks.
                for rule, result, affected in summaries()[2:]:
                    db.state["qa"][(context.batch_id, rule, "batch")] = (result, affected)
            if name == "publish" and not db.noop_publish:
                db.state["batches"][context.batch_id]["status"] = "succeeded"
                db.state["current"][context.dataset_kind] = context.batch_id
                db.phase = "publication"
                if db.publish_then_raise:
                    # Simulate a broken external module that committed behind B's back.
                    db.durable = deepcopy(db.state)
                    raise IntakeError("TEST_EXTERNAL_COMMIT", "test publication state changed unexpectedly")
        return module

    for name, component in runner.STAGES.items():
        callbacks[name] = runner.ModuleBinding(callback(name), f"sql/{component}.sql", "scripted-test-v1")

    def connect():
        db.events.append("connect")
        return db

    kwargs = {
        "connect": connect, "prepared_run": build[0], "manifest": frozen,
        "project_root": build[1]["project_root"], "inventory": build[1]["inventory"],
        "modules": runner.BuildModules(**callbacks), "evidence_root": tmp_path / "run-evidence",
        "fp1": FP1Operation("test_binding", "fp1", "test-v1", 160004, "sql/fp1.sql"),
        "supported_mappings": frozen.as_dict()["rules"]["mappings"],
    }
    return db, kwargs


def execute(setup, **changes):
    db, kwargs = setup
    result = runner.run_build(**(kwargs | changes))
    return db, result, result.as_dict()


def seed_current(setup, *, kind="synthetic", digest=DIGEST, current=True):
    db, kwargs = setup
    batch_id = str(uuid4())
    db.state["batches"][batch_id] = {"kind": kind, "status": "succeeded", "digest": digest,
                                      "manifest": kwargs["manifest"].as_dict()}
    if current:
        db.state["current"][kind] = batch_id
    for rule, result, affected in summaries():
        db.state["qa"][(batch_id, rule, "batch")] = (result, affected)
    db.durable = deepcopy(db.state)
    return batch_id


@pytest.mark.parametrize("missing", [*runner.STAGES, "fp1"])
def test_missing_modules_and_fp1_stop_before_connection(setup, missing):
    db, kwargs = setup
    changes = {"fp1": None} if missing == "fp1" else {"modules": replace(kwargs["modules"], **{missing: None})}
    _, result, value = execute(setup, **changes)
    assert result.exit_code == 1 and value["result"] == "failed"
    assert value["error_code"] == ("FP1_UNAVAILABLE" if missing == "fp1" else "MODULE_UNAVAILABLE")
    assert value["batch_id"] is None and db.events == []


@pytest.mark.parametrize("changes,code", [({"version": ""}, "MODULE_VERSION"), ({"code_path": "sql/not-frozen.sql"}, "MODULE_CODE")])
def test_invalid_binding_stops_before_connection(setup, changes, code):
    db, kwargs = setup
    modules = replace(kwargs["modules"], project=replace(kwargs["modules"].project, **changes))
    _, _, value = execute(setup, modules=modules)
    assert value["error_code"] == code and db.events == []


def test_success_uses_one_connection_actual_native_load_and_qa(setup):
    db, result, value = execute(setup)
    assert result.exit_code == 0 and value["result"] == "succeeded"
    assert [event for event in db.events if event.startswith("commit:")] == ["commit:registration", "commit:publication"]
    assert [name for name, _, _ in db.callbacks] == list(runner.STAGES)
    assert len({id(shared) for _, shared, _ in db.callbacks}) == 1
    assert all(context.batch_id == value["batch_id"] and context.run_id == value["run_id"]
               for _, _, context in db.callbacks)
    assert db.events.index("raw_insert") < db.events.index("commit:registration") < db.events.index("module:project")
    assert db.events.index("module:dw") < db.events.index("qa02") < db.events.index("module:qa_c")
    assert db.events.index("module:qa_d") < db.events.index("module:publish") < db.events.index("commit:publication")
    assert db.events[-1] == "close" and "rollback" not in db.events
    assert len(db.durable["raw"]) == 19
    assert len(db.durable["sources"]) == 3 and len(db.durable["resources"]) == 7
    assert len([key for key in db.durable["qa"] if key[1] in REQUIRED_CHECKS[:2]]) == 16
    assert db.durable["batches"][value["batch_id"]]["status"] == "succeeded"
    assert db.durable["current"] == {"synthetic": value["batch_id"]}
    assert value["qa_summary"] == [{"rule_id": r, "result": s, "affected_count": a} for r, s, a in summaries()]
    directory = Path(value["evidence_ref"])
    assert json.loads((directory / "qa02.json").read_text())["rows"][-1]["result"] == "pass"
    assert json.loads((directory / "result.json").read_text()) == value
    assert db.events.count("lock") == 1


def test_busy_has_no_batch_writes_or_commit(setup):
    setup[0].busy = True
    db, result, value = execute(setup)
    assert result.exit_code == 2 and value["result"] == "busy" and value["batch_id"] is None
    assert "stale" not in db.events and not db.callbacks
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in db.calls)
    assert not any(event.startswith("commit:") for event in db.events)
    assert db.events[-2:] == ["rollback", "close"]


def test_running_in_either_mode_requires_recovery_without_mutation(setup):
    setup[0].stale = [(uuid4(), "official"), (uuid4(), "synthetic")]
    db, result, value = execute(setup)
    assert result.exit_code == 1 and value["error_code"] == "RECOVERY_REQUIRED"
    assert value["batch_id"] is None and not db.callbacks
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in db.calls)
    error = json.loads((Path(value["evidence_ref"]) / "error.json").read_text())
    assert len(error["details"]["batches"]) == 2


@pytest.mark.parametrize("stage", ["project", "vault", "canonical", "dw", "qa_c", "qa_d", "publish"])
def test_stage_failure_rolls_back_build_then_persists_failed_attempt(setup, stage):
    setup[0].fail_stage = stage
    db, result, value = execute(setup)
    assert result.exit_code == 1 and value["result"] == "failed" and value["stage"] == stage
    assert db.events.index("rollback") < db.events.index("failure_update") < db.events.index("commit:failure")
    assert [event for event in db.events if event.startswith("commit:")] == ["commit:registration", "commit:failure"]
    assert len(db.durable["raw"]) == 19
    assert not db.durable["layers"] and not db.durable["qa"] and not db.durable["current"]
    failure = db.durable["batches"][value["batch_id"]]
    assert failure["status"] == "failed" and failure["error"]["details"]["row_locator"] == "csv:1"
    assert [name for name, _, _ in db.callbacks][-1] == stage


@pytest.mark.parametrize("phase", ["registration", "publication", "failure"])
@pytest.mark.parametrize("committed", [False, True])
def test_lost_commit_response_stops_without_retry_or_reclassification(setup, phase, committed):
    db, _ = setup
    db.loss_phase = phase
    db.loss_committed = committed
    if phase == "failure":
        db.fail_stage = "vault"
    _, result, value = execute(setup)
    assert result.exit_code == 3 and value["result"] == "unknown_commit"
    assert value["batch_id"] is not None
    index = db.events.index("commit:" + phase)
    assert db.events[index + 1:] == ["close"]
    if phase != "failure":
        assert "failure_update" not in db.events and "rollback" not in db.events
    if phase == "registration":
        assert not db.callbacks
    assert (Path(value["evidence_ref"]) / f"before-{phase}-commit.json").is_file()
    assert "qa_summary" not in value


def test_noop_publication_is_rejected_before_commit(setup):
    setup[0].noop_publish = True
    db, result, value = execute(setup)
    assert result.exit_code == 1 and value["error_code"] == "PUBLICATION_UNCONFIRMED"
    assert "commit:publication" not in db.events and "commit:failure" in db.events
    assert not db.durable["current"] and not db.durable["qa"]


def test_failure_record_cannot_overwrite_an_already_successful_batch(setup):
    setup[0].publish_then_raise = True
    db, result, value = execute(setup)
    assert result.exit_code == 3 and value["result"] == "unknown_commit"
    assert db.durable["batches"][value["batch_id"]]["status"] == "succeeded"
    assert db.durable["current"]["synthetic"] == value["batch_id"]
    assert "failure_update" in db.events and "commit:failure" not in db.events
    assert any(item.get("error_code") == "FAILURE_STATE" for item in value["diagnostics"])


def test_current_match_returns_actual_summary_without_new_writes(setup):
    old_id = seed_current(setup)
    before = deepcopy(setup[0].durable)
    db, result, value = execute(setup)
    assert result.exit_code == 0 and value["result"] == "no_change"
    assert value["batch_id"] == value["previous_batch_id"] == old_id
    assert db.durable == before and not db.callbacks
    assert not any(sql.startswith(("INSERT", "UPDATE")) for sql, _ in db.calls)
    assert not any(event.startswith("commit:") for event in db.events)
    assert value["qa_summary"][-1] == {"rule_id": "QA07_LOCATION", "result": "limited", "affected_count": 2}


@pytest.mark.parametrize("case", ["missing", "duplicate", "block", "wrong_limited", "negative", "pass_affected"])
def test_no_change_does_not_invent_or_accept_invalid_qa_summary(setup, case):
    seed_current(setup)
    rows = summaries()
    if case == "missing":
        rows.pop()
    elif case == "duplicate":
        rows.append(rows[0])
    else:
        result, affected = {"block": ("block", 1), "wrong_limited": ("limited", 1),
                            "negative": ("pass", -1), "pass_affected": ("pass", 1)}[case]
        rows[0] = (rows[0][0], result, affected)
    setup[0].summary_override = rows
    db, _, value = execute(setup)
    assert value["result"] == "failed" and value["error_code"] == "QA_SUMMARY"
    assert "batch_insert" not in db.events and "failure_update" not in db.events


def test_historical_match_does_not_reactivate_old_batch(setup):
    historical = seed_current(setup, current=False)
    current = seed_current(setup, digest="b2" * 32)
    db, _, value = execute(setup)
    assert value["result"] == "succeeded"
    assert value["previous_batch_id"] == current and value["batch_id"] not in {historical, current}
    assert db.durable["batches"][historical]["status"] == "succeeded"
    assert db.durable["batches"][current]["status"] == "succeeded"


def test_synthetic_run_does_not_select_or_replace_official_pointer(setup):
    official = seed_current(setup, kind="official")
    db, _, value = execute(setup)
    assert value["result"] == "succeeded" and value["previous_batch_id"] is None
    assert db.durable["current"] == {"official": official, "synthetic": value["batch_id"]}
    assert all(parameters == ("synthetic",) for sql, parameters in db.calls if "FROM meta.current_release" in sql)


def test_current_pointer_with_wrong_mode_is_rejected(setup):
    _, kwargs = setup
    setup[0].current_override = [(str(uuid4()), "succeeded", "official", "succeeded", DIGEST, kwargs["manifest"].as_dict())]
    db, _, value = execute(setup)
    assert value["error_code"] == "CURRENT_RELEASE" and not db.callbacks
    assert "source" not in db.events


@pytest.mark.parametrize("failure", ["close", "evidence"])
def test_postcommit_cleanup_error_does_not_relabel_success(setup, monkeypatch, failure):
    if failure == "close":
        setup[0].close_error = True
    else:
        write = runner.write_evidence

        def fail_result(path, value):
            if Path(path).name == "result.json":
                raise OSError("simulated result write error")
            return write(path, value)

        monkeypatch.setattr(runner, "write_evidence", fail_result)
    db, result, value = execute(setup)
    assert result.exit_code == 0 and value["result"] == "succeeded"
    assert db.durable["batches"][value["batch_id"]]["status"] == "succeeded"
    assert value["diagnostics"] and "failure_update" not in db.events


def test_raw_qa_block_rolls_back_and_retains_file_evidence(setup):
    setup[0].corrupt_raw = True
    db, _, value = execute(setup)
    assert value["result"] == "failed" and value["stage"] == "raw" and value["error_code"] == "QA_BLOCK"
    assert "module:qa_c" not in db.events and not db.durable["qa"]
    report = json.loads((Path(value["evidence_ref"]) / "qa02.json").read_text())
    assert report["rows"][-1]["result"] == "block"
    assert report["rows"][-1]["actual"]["metrics"]["block_count"] == 1
    assert len(db.durable["raw"]) == 19


def test_missing_mapping_support_blocks_before_fp1_or_registration(setup):
    db, _, value = execute(setup, supported_mappings=())
    assert value["error_code"] == "QA_BLOCK" and value["stage"] == "input" and value["batch_id"] is None
    assert "fp1" not in db.events and "source" not in db.events
    report = json.loads((Path(value["evidence_ref"]) / "qa01.json").read_text())
    assert report["rows"][-1]["actual"]["metrics"]["block_count"] == 7


def test_rollback_failure_does_not_write_failed_status(setup):
    setup[0].fail_stage = "vault"
    setup[0].rollback_error = True
    db, result, value = execute(setup)
    assert result.exit_code == 3 and value["result"] == "unknown_commit"
    assert "failure_update" not in db.events


def test_module_facade_has_no_transaction_lifecycle_or_cursor_escape():
    db = ScriptedConnection()
    shared = runner.ModuleConnection(db)
    for name in ("commit", "rollback", "close"):
        with pytest.raises(AttributeError):
            getattr(shared, name)()
    with pytest.raises(AttributeError):
        shared.autocommit = True
    with shared.cursor() as cursor:
        with pytest.raises(AttributeError):
            _ = cursor.connection
    assert not db.closed and not db.events
