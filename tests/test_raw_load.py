"""Loader validation and calls with a scripted connection, not a PostgreSQL server."""
from collections import deque
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.raw_load import RawLoader, load_prepared


ROOT = Path(__file__).resolve().parents[1]
SOURCE = {
    "source_id": "syn_test", "jurisdiction_code": "TEST",
    "source_name": "Synthetic test source", "publisher": "ARSIA team",
}
FILE = {
    "source_id": "syn_test", "resource_id": "syn_test_crash",
    "resource_role": "crash", "entity_kind": "crash", "file_sha256": "1" * 64,
    "parser_version": "csv-native-v1", "locator_version": "csv-logical-v1",
    "format": "csv", "encoding": "utf-8", "sheet": None, "header_row": 1,
    "header": ["ID", "empty", "missing", "token", "space"], "raw_count": 1,
}
PAYLOAD = {"ID": "0001", "empty": "", "missing": None, "token": "NA", "space": "  "}
RAW_ID = UUID("9c9f8996-40c5-4672-9899-6f9f2f229ca2")


class ScriptedConnection:
    """Supply query replies without implementing SQL or transaction semantics."""

    def __init__(self, replies=(), *, autocommit=False):
        self.autocommit = autocommit
        self.replies = deque(replies)
        self.calls = []

    def cursor(self):
        return ScriptedCursor(self)

    def commit(self):
        pytest.fail("The loader must leave commit to its caller")

    def rollback(self):
        pytest.fail("The loader must leave rollback to its caller")

    def close(self):
        pytest.fail("The caller owns the connection")


class ScriptedCursor:
    def __init__(self, connection):
        self.connection = connection
        self.reply = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def close(self):
        pass

    def execute(self, statement, parameters=None):
        self.connection.calls.append((str(statement), parameters))
        if not self.connection.replies:
            pytest.fail(f"Unexpected query: {statement}")
        self.reply = self.connection.replies.popleft()
        if isinstance(self.reply, Exception):
            raise self.reply
        return self

    def fetchone(self):
        return self.reply


def l1(**changes):
    row = {name: FILE[name] for name in (
        "source_id", "resource_id", "file_sha256", "parser_version")}
    row.update(row_locator="csv:1", payload=deepcopy(PAYLOAD))
    row.update(changes)
    return row


def loader(connection, *, sources=None, files=None, dataset_kind="synthetic"):
    return RawLoader(connection, dataset_kind=dataset_kind,
                     sources=deepcopy(sources if sources is not None else [SOURCE]),
                     files=deepcopy(files if files is not None else [FILE]))


def registration_replies(sources=None, files=None):
    replies = []
    for source in sorted(sources if sources is not None else [SOURCE], key=lambda row: row["source_id"]):
        replies.extend([None, tuple(source[field] for field in (
            "source_id", "jurisdiction_code", "source_name", "publisher"))])
    for file in sorted(files if files is not None else [FILE], key=lambda row: row["resource_id"]):
        replies.extend([None, tuple(file[field] for field in (
            "resource_id", "source_id", "resource_role", "entity_kind"))])
    return replies


@pytest.fixture
def prepared_s0(tmp_path):
    result = prepare(ROOT / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert result["status"] == "prepared"
    sources = json.loads((ROOT / "tests/fixtures/s0/contract.json").read_text())["sources"]
    return Path(result["run_dir"]), sources, result


def rewrite_json(path, change):
    value = json.loads(path.read_text())
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_autocommit_connection_is_rejected():
    connection = ScriptedConnection(autocommit=True)
    with pytest.raises(IntakeError) as error:
        loader(connection)
    assert error.value.code == "RAW_AUTOCOMMIT"
    assert connection.calls == []


def test_registration_is_required_before_rows():
    connection = ScriptedConnection()
    with pytest.raises(IntakeError):
        loader(connection).load_record(l1())
    assert connection.calls == []


def test_identical_registration_can_be_repeated():
    connection = ScriptedConnection(registration_replies() * 2)
    subject = loader(connection)
    subject.register()
    subject.register()
    assert not connection.replies
    assert all("DO UPDATE" not in query.upper() for query, _ in connection.calls)


def test_changed_source_metadata_requires_review():
    connection = ScriptedConnection([
        None, ("syn_test", "TEST", "Different registered name", "ARSIA team"),
    ])
    subject = loader(connection)
    with pytest.raises(IntakeError) as error:
        subject.register()
    assert error.value.code == "REGISTRATION_CONFLICT"
    assert not connection.replies
    with pytest.raises(IntakeError):
        subject.load_record(l1())


@pytest.mark.parametrize("registered", [
    ("syn_test_crash", "syn_other", "crash", "crash"),
    ("syn_test_crash", "syn_test", "vehicle", "unit"),
])
def test_existing_resource_cannot_be_reassigned(registered):
    connection = ScriptedConnection(registration_replies()[:2] + [None, registered])
    subject = loader(connection)
    with pytest.raises(IntakeError) as error:
        subject.register()
    assert error.value.code == "REGISTRATION_CONFLICT"
    assert not connection.replies


def test_transaction_mode_is_checked_again_before_registration():
    connection = ScriptedConnection()
    subject = loader(connection)
    connection.autocommit = True
    with pytest.raises(IntakeError) as error:
        subject.register()
    assert error.value.code == "RAW_AUTOCOMMIT"
    assert connection.calls == []


def test_insert_binds_native_values_and_returns_database_uuid():
    connection = ScriptedConnection(registration_replies() + [(RAW_ID,)])
    subject = loader(connection)
    subject.register()
    row = l1()
    original = deepcopy(row)
    result = subject.load_record(row)
    assert result.raw_record_id == RAW_ID
    assert result.inserted is True
    assert row == original
    statement, parameters = connection.calls[-1]
    assert "ON CONFLICT" in statement.upper()
    assert "RETURNING" in statement.upper()
    assert "0001" not in statement
    payload_parameters = [json.loads(value) for value in parameters
                          if isinstance(value, str) and value.startswith("{")]
    assert payload_parameters == [PAYLOAD]
    assert "csv:1" in parameters
    assert FILE["file_sha256"] in parameters
    assert not connection.replies


def test_replay_returns_the_existing_uuid():
    connection = ScriptedConnection(registration_replies() + [None, (RAW_ID, "syn_test", True)])
    subject = loader(connection)
    subject.register()
    result = subject.load_record(l1())
    assert result.raw_record_id == RAW_ID
    assert result.inserted is False
    assert not connection.replies


def test_same_identity_with_changed_payload_blocks_without_updating_raw():
    connection = ScriptedConnection(registration_replies() + [None, (RAW_ID, "syn_test", False)])
    subject = loader(connection)
    subject.register()
    row = l1()
    row["payload"]["empty"] = None
    with pytest.raises(IntakeError) as error:
        subject.load_record(row)
    assert error.value.code == "RAW_PAYLOAD_CONFLICT"
    assert all("DO UPDATE" not in query.upper() for query, _ in connection.calls)
    assert not connection.replies


def test_identical_payload_at_different_native_positions_keeps_two_ids():
    other_id = UUID("7b4d0c72-bf58-4744-bb4c-a5c638fa47f6")
    connection = ScriptedConnection(registration_replies() + [(RAW_ID,), (other_id,)])
    subject = loader(connection)
    subject.register()
    first = subject.load_record(l1(row_locator="csv:1"))
    second = subject.load_record(l1(row_locator="csv:2"))
    assert first.raw_record_id != second.raw_record_id
    assert "csv:1" in connection.calls[-2][1]
    assert "csv:2" in connection.calls[-1][1]
    assert not connection.replies


@pytest.mark.parametrize("changed_field,value", [
    ("source_id", "official_test"), ("resource_id", "official_test_crash"),
])
def test_synthetic_loader_rejects_official_identifiers(changed_field, value):
    file = deepcopy(FILE)
    file[changed_field] = value
    connection = ScriptedConnection()
    with pytest.raises(IntakeError):
        loader(connection, files=[file])
    assert connection.calls == []


def test_unknown_source_is_not_inferred_from_resource_id():
    connection = ScriptedConnection()
    with pytest.raises(IntakeError):
        loader(connection, sources=[])
    assert connection.calls == []


@pytest.mark.parametrize("change", [
    lambda row: row["payload"].update(ID=1),
    lambda row: row["payload"].update(ID=True),
    lambda row: row["payload"].update(ID=["0001"]),
    lambda row: row["payload"].update(extra="unexpected"),
    lambda row: row["payload"].pop("empty"),
    lambda row: row.update(source_id="syn_another"),
    lambda row: row.update(batch_id="not-an-L1-member"),
    lambda row: row.pop("parser_version"),
])
def test_invalid_l1_is_rejected_before_raw_sql(change):
    connection = ScriptedConnection(registration_replies())
    subject = loader(connection)
    subject.register()
    before = len(connection.calls)
    row = l1()
    change(row)
    with pytest.raises(IntakeError):
        subject.load_record(row)
    assert len(connection.calls) == before


@pytest.mark.parametrize("status", ["preparing", "failed"])
def test_incomplete_preparation_is_not_loadable(prepared_s0, status):
    directory, sources, _ = prepared_s0
    rewrite_json(directory / "run.json", lambda run: run.update(status=status))
    connection = ScriptedConnection()
    with pytest.raises(IntakeError):
        load_prepared(connection, directory, sources)
    assert connection.calls == []


def test_changed_jsonl_is_rejected_before_registration(prepared_s0):
    directory, sources, run = prepared_s0
    records = directory / run["files"][0]["records_path"]
    records.write_bytes(records.read_bytes() + b"\n")
    connection = ScriptedConnection()
    with pytest.raises(IntakeError):
        load_prepared(connection, directory, sources)
    assert connection.calls == []


def test_changed_archive_is_rejected_before_registration(prepared_s0):
    directory, sources, _ = prepared_s0
    provenance = json.loads((directory / "provenance.json").read_text())
    output_root = directory.parents[2]
    archive = output_root / provenance["files"][0]["archive_relpath"]
    archive.write_bytes(b"changed archive")
    connection = ScriptedConnection()
    with pytest.raises(IntakeError):
        load_prepared(connection, directory, sources)
    assert connection.calls == []


def test_provenance_cannot_reassign_a_resource_hash(prepared_s0):
    directory, sources, _ = prepared_s0
    rewrite_json(directory / "provenance.json", lambda provenance:
                 provenance["files"][0].update(file_sha256="f" * 64))
    connection = ScriptedConnection()
    with pytest.raises(IntakeError):
        load_prepared(connection, directory, sources)
    assert connection.calls == []


def test_prepared_s0_streams_all_native_rows_to_the_supplied_connection(prepared_s0):
    directory, sources, run = prepared_s0
    raw_ids = [UUID(int=number) for number in range(1, 20)]
    files = json.loads((directory / "files.json").read_text())["files"]
    replies = registration_replies(sources, files)
    replies.extend((raw_id,) for raw_id in raw_ids)
    connection = ScriptedConnection(replies)
    received = []
    result = load_prepared(connection, directory, sources,
                           on_record=lambda row, loaded: received.append((row, loaded)))
    assert (result.raw_count, result.inserted_count, result.reused_count) == (19, 19, 0)
    assert result.dataset_kind == "synthetic"
    assert str(result.run_id) == run["run_id"]
    assert [loaded.raw_record_id for _, loaded in received] == raw_ids
    assert len({row["resource_id"] for row, _ in received}) == 7
    assert [row["payload"] for row, _ in received if row["resource_id"] == "syn_vic_node"] == [
        json.loads(line)["payload"]
        for line in (directory / "records/syn_vic_node.jsonl").read_text().splitlines()
    ]
    assert not connection.replies


def test_callback_failure_stops_loading_and_leaves_rollback_to_caller(prepared_s0):
    directory, sources, _ = prepared_s0
    files = json.loads((directory / "files.json").read_text())["files"]
    connection = ScriptedConnection(registration_replies(sources, files) + [(RAW_ID,)])

    def failed_callback(row, result):
        assert result.raw_record_id == RAW_ID
        raise RuntimeError("Cannot store the lineage receipt")

    with pytest.raises(RuntimeError, match="Cannot store the lineage receipt"):
        load_prepared(connection, directory, sources, on_record=failed_callback)
    assert not connection.replies


def test_prepared_duplicate_position_is_not_treated_as_another_native_row(prepared_s0):
    directory, sources, run = prepared_s0
    file = run["files"][0]
    path = directory / file["records_path"]
    lines = path.read_bytes().splitlines(keepends=True)
    lines[1] = lines[0]
    path.write_bytes(b"".join(lines))
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    rewrite_json(directory / "run.json", lambda receipt:
                 receipt["files"][0].update(records_sha256=checksum))
    files = json.loads((directory / "files.json").read_text())["files"]
    connection = ScriptedConnection(registration_replies(sources, files) + [(RAW_ID,)])
    with pytest.raises(IntakeError, match="Repeated or out-of-order"):
        load_prepared(connection, directory, sources)
    assert not connection.replies


def test_duplicate_json_payload_key_is_rejected_even_with_a_matching_receipt(prepared_s0):
    directory, sources, run = prepared_s0
    path = directory / run["files"][0]["records_path"]
    content = path.read_bytes().replace(b'"Crash ID":"0001"', b'"Crash ID":"0001","Crash ID":"0002"', 1)
    assert content != path.read_bytes()
    path.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    rewrite_json(directory / "run.json", lambda receipt:
                 receipt["files"][0].update(records_sha256=checksum))
    files = json.loads((directory / "files.json").read_text())["files"]
    connection = ScriptedConnection(registration_replies(sources, files))
    with pytest.raises(IntakeError, match="Duplicate JSON member"):
        load_prepared(connection, directory, sources)
    assert not connection.replies
