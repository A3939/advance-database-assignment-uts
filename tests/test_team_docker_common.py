"""Reject unsafe team database setup without touching an existing database."""

import importlib.util
import json
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict


MODULE = Path(__file__).resolve().parents[1] / "docker/team/common.py"
spec = importlib.util.spec_from_file_location("team_common", MODULE)
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class ReadOnlyConnection:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def execute(self, statement, arguments=None):
        assert statement.lstrip().startswith("SELECT"), statement
        self.calls.append((statement, arguments))
        return Result(next(self.results))


@pytest.mark.parametrize("role", ("owner", "loader", "reader"))
def test_role_credentials_are_separate_and_quoted(monkeypatch, role):
    for key in common.PASSWORDS.values():
        monkeypatch.setenv(key, "different-" + key)
    secret = "local ' password \\ with spaces"
    monkeypatch.setenv(common.PASSWORDS[role], secret)
    monkeypatch.setenv("ARSIA_DB_HOST", "acceptance-db")
    parsed = conninfo_to_dict(common.dsn(role))
    assert parsed["password"] == secret
    assert parsed["user"] == common.ROLES[role]
    assert parsed["host"] == "acceptance-db" and parsed["dbname"] == "arsia"
    assert parsed["port"] == "5432"


def test_missing_or_unknown_role_fails_before_connecting(monkeypatch):
    monkeypatch.delenv("ARSIA_LOADER_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="ARSIA_LOADER_PASSWORD"):
        common.dsn("loader")
    with pytest.raises(ValueError, match="owner, loader or reader"):
        common.dsn("migrator")


@pytest.mark.parametrize("position", range(4))
def test_unmarked_partial_or_foreign_database_is_refused(position):
    results = [[], [], [], []]
    results[position] = [("existing-object",)]
    connection = ReadOnlyConnection(results)
    with pytest.raises(ValueError, match="unmarked or partially"):
        common._fresh_database(connection)
    assert len(connection.calls) == 4


def test_empty_database_check_only_reads_catalogues():
    connection = ReadOnlyConnection([[], [], [], []])
    common._fresh_database(connection)
    assert len(connection.calls) == 4


@pytest.mark.parametrize("change", ("missing", "migration", "catalog", "audit", "wrong-type"))
def test_installation_drift_is_refused(change):
    expected = {"version": common.STAMP_VERSION, "build_inventory_sha256": "original"}
    actual = {"tables": {"meta.source": [["source_id", "text", False]]}}
    stamp = {**expected, "catalog_sha256": common._catalog_hash(actual), "a03_initial_audit": "passed"}
    if change == "missing":
        stamp = None
    elif change == "migration":
        stamp["build_inventory_sha256"] = "different"
    elif change == "catalog":
        actual["tables"]["meta.source"][0][2] = True
    elif change == "audit":
        stamp["a03_initial_audit"] = "not_run"
    else:
        stamp = []
    with pytest.raises(ValueError):
        common._require_stamp(stamp, expected, actual)


def test_matching_stamp_does_not_need_migrations():
    actual = {"tables": {"meta.source": [["source_id", "text", False]]}}
    expected = {"version": common.STAMP_VERSION}
    stamp = {**expected, "catalog_sha256": common._catalog_hash(actual), "a03_initial_audit": "passed"}
    common._require_stamp(stamp, expected, actual)


def test_a03_adapter_removes_only_the_known_psql_setting():
    original = (MODULE.parents[2] / "sql/tests/a03_database_roles.sql").read_text(encoding="utf-8")
    adapted = common._strip_psql(original)
    assert adapted == original.replace("\\set ON_ERROR_STOP on\n", "")
    assert adapted.endswith("ROLLBACK;\n")
    with pytest.raises(ValueError, match="Unsupported psql"):
        common._strip_psql("\\include other.sql\n")


@pytest.mark.parametrize("offset,value", ((0,"160016"), (1,"LATIN1"), (3,"Australia/Sydney"), (5,"arsia_owner")))
def test_wrong_server_or_loader_login_is_refused(offset, value):
    row = ["160015", "UTF8", "UTF8", "UTC", "arsia", "arsia_loader", "arsia_loader"]
    row[offset] = value
    with pytest.raises(ValueError, match="PostgreSQL 16.15"):
        common._environment(ReadOnlyConnection([[tuple(row)]]), "loader")


def test_inventory_escape_and_changed_bytes_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "ROOT", tmp_path)
    (tmp_path / "resource.sql").write_text("SELECT 1;\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        common._file_record({"path": "resource.sql", "sha256": "wrong"})
    with pytest.raises(ValueError, match="unsafe"):
        common._file_record({"path": "../escape.sql", "sha256": "wrong"})


def test_receipt_json_uses_utf8(tmp_path):
    path = tmp_path / "receipt.json"
    common.write(path, {"status": "passed", "note": "课程"})
    assert "课程" in path.read_text(encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "passed"
