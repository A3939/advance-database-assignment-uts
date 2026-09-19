"""Adapter checks with scripted replies; these do not execute PostgreSQL or FP1."""
from collections import deque
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
import json

import pytest

from arsia_ingest.fingerprint import FP1Operation, fingerprint
from arsia_ingest.models import IntakeError


DIGEST = "0123456789abcdef" * 4
ENVIRONMENT = [("160004", "UTF8", "UTF8", "UTC")]


class FrozenStub:
    def __init__(self, manifest):
        self.manifest = deepcopy(manifest)

    def as_dict(self):
        return deepcopy(self.manifest)

    def fingerprint_input(self):
        value = self.as_dict()
        del value["provenance"]
        return value


class ScriptedConnection:
    def __init__(self, replies=(), *, autocommit=False):
        self.replies = deque(replies)
        self.calls = []
        self.autocommit = autocommit
        self.cursor_closed = False

    def cursor(self):
        return ScriptedCursor(self)

    def commit(self):
        pytest.fail("The caller owns commit")

    def rollback(self):
        pytest.fail("The caller owns rollback")

    def close(self):
        pytest.fail("The caller owns the connection")


class ScriptedCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connection.cursor_closed = True

    def execute(self, statement, parameters=None):
        self.connection.calls.append((statement, parameters))
        if not self.connection.replies:
            pytest.fail(f"Unexpected SQL call: {statement}")
        self.rows = self.connection.replies.popleft()
        if isinstance(self.rows, Exception):
            raise self.rows

    def fetchall(self):
        return self.rows


@pytest.fixture
def binding(tmp_path):
    path = tmp_path / "sql" / "fp1.sql"
    path.parent.mkdir()
    path.write_text("-- Test bytes, not an FP1 implementation.\n", encoding="utf-8")
    operation = FP1Operation("review_test", "fp1", "test-v1", 160004, "sql/fp1.sql")
    manifest = FrozenStub({
        "contract_version": "team-v1.1", "dataset_kind": "synthetic",
        "rules": {"code_files": [{"path": "sql/fp1.sql", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]},
        "provenance": {"prepared_at": "2026-09-19T00:00:00Z", "local_note": "not fingerprint input"},
    })
    return operation, manifest, tmp_path


def call(binding, connection=None, operation=None):
    chosen, manifest, root = binding
    if connection is None:
        connection = ScriptedConnection([ENVIRONMENT, [(True,)], [(DIGEST,)]])
    return fingerprint(connection, manifest, chosen if operation is None else operation, project_root=root)


def test_missing_operation_fails_without_database_or_manifest_access(tmp_path):
    with pytest.raises(IntakeError) as error:
        fingerprint(None, None, project_root=tmp_path)
    assert error.value.code == "FP1_UNAVAILABLE"


def test_calls_only_supplied_function_and_returns_sql_value(binding):
    connection = ScriptedConnection([ENVIRONMENT, [(True,)], [(DIGEST,)]])
    before = binding[1].as_dict()
    assert call(binding, connection) == DIGEST
    assert connection.calls[1][1] == ("review_test", "fp1")
    statement, parameters = connection.calls[2]
    assert statement == 'SELECT "review_test"."fp1"(%s::jsonb)'
    assert json.loads(parameters[0]) == binding[1].fingerprint_input()
    assert "provenance" not in json.loads(parameters[0])
    assert binding[1].as_dict() == before
    assert not connection.replies
    assert connection.cursor_closed


@pytest.mark.parametrize("changes", [
    {"schema": "x; DROP TABLE y"}, {"name": 'fn"bad'}, {"name": ""},
    {"name": "x" * 64}, {"protocol": "FP2"}, {"implementation_version": ""},
    {"implementation_version": "draft version"}, {"postgres_version_num": "160004"},
    {"postgres_version_num": True}, {"postgres_version_num": 150004},
    {"postgres_version_num": 170000}, {"code_path": "/tmp/fp1.sql"},
    {"code_path": "../fp1.sql"}, {"code_path": "sql/../fp1.sql"},
    {"code_path": "sql\\fp1.sql"}, {"code_path": "./sql/fp1.sql"},
])
def test_invalid_binding_is_rejected_before_sql(binding, changes):
    connection = ScriptedConnection()
    with pytest.raises(IntakeError) as error:
        call(binding, connection, replace(binding[0], **changes))
    assert error.value.code == "FP1_BINDING"
    assert connection.calls == []


def test_binding_is_immutable(binding):
    with pytest.raises(FrozenInstanceError):
        binding[0].name = "another"


@pytest.mark.parametrize("autocommit", [True, None, 0])
def test_caller_transaction_is_required(binding, autocommit):
    connection = ScriptedConnection(autocommit=autocommit)
    with pytest.raises(IntakeError) as error:
        call(binding, connection)
    assert error.value.code == "FP1_AUTOCOMMIT"
    assert connection.calls == []


@pytest.mark.parametrize("change", ["missing", "duplicate", "changed", "absent", "bad_hash", "outside"])
def test_sql_file_must_match_frozen_code_inventory(binding, tmp_path, change):
    operation, manifest, root = binding
    files = manifest.manifest["rules"]["code_files"]
    if change == "missing":
        files.clear()
    elif change == "duplicate":
        files.append(deepcopy(files[0]))
    elif change == "changed":
        (root / operation.code_path).write_text("-- changed\n")
    elif change == "absent":
        (root / operation.code_path).unlink()
    elif change == "bad_hash":
        files[0]["sha256"] = "not-a-hash"
    elif change == "outside":
        outside = tmp_path.parent / (tmp_path.name + "-outside.sql")
        outside.write_bytes((root / operation.code_path).read_bytes())
        (root / operation.code_path).unlink()
        (root / operation.code_path).symlink_to(outside)
    connection = ScriptedConnection()
    with pytest.raises(IntakeError) as error:
        call(binding, connection)
    assert error.value.code == "FP1_CODE"
    assert connection.calls == []


@pytest.mark.parametrize("environment", [
    [], [("160004", "UTF8", "UTF8", "UTC")] * 2,
    [("150004", "UTF8", "UTF8", "UTC")], [("160005", "UTF8", "UTF8", "UTC")],
    [("160004", "LATIN1", "UTF8", "UTC")], [("160004", "UTF8", "LATIN1", "UTC")],
    [("160004", "UTF8", "UTF8", "Australia/Sydney")], [("160004",)],
])
def test_database_environment_must_match_binding(binding, environment):
    connection = ScriptedConnection([environment])
    with pytest.raises(IntakeError) as error:
        call(binding, connection)
    assert error.value.code == "FP1_ENVIRONMENT"
    assert len(connection.calls) == 1
    assert connection.cursor_closed


@pytest.mark.parametrize("signature", [[], [(False,)], [(True,), (True,)]])
def test_missing_or_incompatible_function_is_unavailable(binding, signature):
    connection = ScriptedConnection([ENVIRONMENT, signature])
    with pytest.raises(IntakeError) as error:
        call(binding, connection)
    assert error.value.code == "FP1_UNAVAILABLE"
    assert len(connection.calls) == 2


@pytest.mark.parametrize("result", [
    [], [(None,)], [(DIGEST.upper(),)], [("a" * 63,)], [("g" * 64,)],
    [(DIGEST, DIGEST)], [(DIGEST,), (DIGEST,)],
])
def test_invalid_sql_result_never_becomes_a_fingerprint(binding, result):
    connection = ScriptedConnection([ENVIRONMENT, [(True,)], result])
    with pytest.raises(IntakeError) as error:
        call(binding, connection)
    assert error.value.code == "FP1_RESULT"
    assert connection.cursor_closed


def test_database_failure_is_left_to_callers_rollback(binding):
    failure = RuntimeError("scripted database failure")
    connection = ScriptedConnection([ENVIRONMENT, [(True,)], failure])
    with pytest.raises(RuntimeError, match="scripted database failure"):
        call(binding, connection)
    assert connection.cursor_closed
