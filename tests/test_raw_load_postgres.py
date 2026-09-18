"""Opt-in tests against A's migrated PostgreSQL 16 test database.

Set ARSIA_TEST_DSN to a loader connection. These tests install nothing, use
unique synthetic IDs, and roll back every database write.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Real PostgreSQL tests require A's migrated database and ARSIA_TEST_DSN",
)


@pytest.fixture
def connection():
    dsn = os.environ.get("ARSIA_TEST_DSN")
    if not dsn:
        pytest.fail("ARSIA_TEST_DSN is set but empty", pytrace=False)
    try:
        import psycopg
    except ImportError:
        pytest.fail("ARSIA_TEST_DSN is set but psycopg is not installed", pytrace=False)
    try:
        conn = psycopg.connect(dsn, autocommit=False, connect_timeout=10)
    except psycopg.Error as exc:
        pytest.fail(f"Cannot connect to the configured test database ({type(exc).__name__})",
                    pytrace=False)
    try:
        assert conn.info.server_version // 10000 == 16, "The team baseline requires PostgreSQL 16"
        assert conn.execute("SHOW server_encoding").fetchone()[0] == "UTF8"
        assert conn.execute("SHOW TimeZone").fetchone()[0] == "UTC"
        for table in ("meta.source", "meta.resource", "raw.record"):
            assert conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0], (
                f"A's migration has not installed {table}")
            privileges = conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT'), "
                "has_table_privilege(current_user, %s, 'INSERT')", (table, table),
            ).fetchone()
            assert privileges == (True, True), f"The test loader needs SELECT and INSERT on {table}"
        conn.rollback()
        yield conn
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def s0(tmp_path):
    fixture_dir = ROOT / "tests/fixtures/s0"
    config = json.loads((fixture_dir / "config.json").read_text(encoding="utf-8"))
    sources = json.loads((fixture_dir / "contract.json").read_text(encoding="utf-8"))["sources"]
    prefix = f"syn_b08_{uuid4().hex}_"

    def namespaced(value):
        return prefix + value.removeprefix("syn_")

    for resource in config["resources"]:
        resource["source_id"] = namespaced(resource["source_id"])
        resource["resource_id"] = namespaced(resource["resource_id"])
        resource["path"] = str(fixture_dir / resource["path"])
    for source in sources:
        source["source_id"] = namespaced(source["source_id"])
        source["resource_ids"] = [namespaced(value) for value in source["resource_ids"]]
    config_path = tmp_path / "inputs.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    receipt = prepare(config_path, tmp_path / "intake")
    assert (receipt["status"], receipt["raw_count"]) == ("prepared", 19)
    run_dir = Path(receipt["run_dir"])
    files = json.loads((run_dir / "files.json").read_text(encoding="utf-8"))["files"]
    rows = []
    for item in receipt["files"]:
        rows.extend(json.loads(line) for line in
                    (run_dir / item["records_path"]).read_text(encoding="utf-8").splitlines())
    return {"run_dir": run_dir, "sources": sources, "files": files, "rows": rows}


def stored_rows(connection, s0):
    resource_ids = [item["resource_id"] for item in s0["files"]]
    return connection.execute(
        "SELECT resource_id, row_locator, raw_record_id, ingested_at, source_id, "
        "file_sha256, parser_version, payload FROM raw.record "
        "WHERE resource_id = ANY(%s) ORDER BY resource_id, row_locator", (resource_ids,),
    ).fetchall()


def test_postgres_s0_load_is_lossless_and_reuses_ids(connection, s0):
    from arsia_ingest.raw_load import load_prepared

    accepted = []
    first = load_prepared(connection, s0["run_dir"], s0["sources"],
                          on_record=lambda row, result: accepted.append((row, result)))
    assert (first.raw_count, first.inserted_count, first.reused_count) == (19, 19, 0)
    assert len(accepted) == 19
    assert all(isinstance(result.raw_record_id, UUID) and result.inserted for _, result in accepted)
    source_ids = [source["source_id"] for source in s0["sources"]]
    assert connection.execute(
        "SELECT count(*) FROM meta.source WHERE source_id = ANY(%s)", (source_ids,),
    ).fetchone()[0] == 3
    assert connection.execute(
        "SELECT count(*) FROM meta.resource WHERE source_id = ANY(%s)", (source_ids,),
    ).fetchone()[0] == 7

    before = stored_rows(connection, s0)
    assert len(before) == 19
    expected = {(row["resource_id"], row["row_locator"]): row for row in s0["rows"]}
    for resource_id, locator, _, _, source_id, digest, parser, payload in before:
        native = expected[(resource_id, locator)]
        assert (source_id, digest, parser, payload) == (
            native["source_id"], native["file_sha256"], native["parser_version"], native["payload"])
    nodes = [row for row in before if row[0].endswith("_vic_node")]
    assert {row[1] for row in nodes} == {"csv:1", "csv:2", "csv:3", "csv:4"}
    assert len({row[2] for row in nodes}) == 4

    repeated = []
    second = load_prepared(connection, s0["run_dir"], s0["sources"],
                           on_record=lambda row, result: repeated.append((row, result)))
    assert (second.raw_count, second.inserted_count, second.reused_count) == (19, 0, 19)
    assert [result.raw_record_id for _, result in repeated] == [
        result.raw_record_id for _, result in accepted]
    assert all(not result.inserted for _, result in repeated)
    assert stored_rows(connection, s0) == before


def test_postgres_existing_raw_timestamp_is_not_rewritten(connection, s0):
    from arsia_ingest.raw_load import RawLoader

    loader = RawLoader(connection, dataset_kind="synthetic", sources=s0["sources"], files=s0["files"])
    loader.register()
    row = s0["rows"][0]
    raw_id = uuid4()
    original_time = datetime(2000, 1, 1, tzinfo=timezone.utc)
    connection.execute(
        "INSERT INTO raw.record (raw_record_id, resource_id, source_id, file_sha256, "
        "parser_version, row_locator, payload, ingested_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)",
        (raw_id, row["resource_id"], row["source_id"], row["file_sha256"], row["parser_version"],
         row["row_locator"], json.dumps(row["payload"]), original_time),
    )
    result = loader.load_record(row)
    assert (result.raw_record_id, result.inserted) == (raw_id, False)
    assert connection.execute(
        "SELECT ingested_at, payload FROM raw.record WHERE raw_record_id = %s", (raw_id,),
    ).fetchone() == (original_time, row["payload"])


def test_postgres_payload_conflict_preserves_original(connection, s0):
    from arsia_ingest.raw_load import RawLoader

    loader = RawLoader(connection, dataset_kind="synthetic", sources=s0["sources"], files=s0["files"])
    loader.register()
    original = s0["rows"][0]
    accepted = loader.load_record(original)
    changed = deepcopy(original)
    changed["payload"]["Crash ID"] = "changed"
    with pytest.raises(IntakeError) as error:
        with connection.transaction():
            loader.load_record(changed)
    assert error.value.code == "RAW_PAYLOAD_CONFLICT"
    assert connection.execute(
        "SELECT payload FROM raw.record WHERE raw_record_id = %s", (accepted.raw_record_id,),
    ).fetchone()[0] == original["payload"]
    assert len(stored_rows(connection, s0)) == 1


def test_postgres_resource_identity_cannot_be_reassigned(connection, s0):
    from arsia_ingest.raw_load import RawLoader

    loader = RawLoader(connection, dataset_kind="synthetic", sources=s0["sources"], files=s0["files"])
    loader.register()
    changed = deepcopy(s0["files"])
    changed[0]["resource_role"] = "unit"
    with pytest.raises(IntakeError) as error:
        with connection.transaction():
            RawLoader(connection, dataset_kind="synthetic", sources=s0["sources"], files=changed).register()
    assert error.value.code == "REGISTRATION_CONFLICT"
    assert connection.execute(
        "SELECT resource_role FROM meta.resource WHERE resource_id = %s",
        (s0["files"][0]["resource_id"],),
    ).fetchone()[0] == s0["files"][0]["resource_role"]


def test_postgres_synthetic_ids_cannot_enter_official_mode(connection, s0):
    from arsia_ingest.raw_load import RawLoader

    with pytest.raises(IntakeError):
        with connection.transaction():
            RawLoader(connection, dataset_kind="official", sources=s0["sources"],
                      files=s0["files"]).register()
    assert stored_rows(connection, s0) == []
    assert connection.execute(
        "SELECT count(*) FROM meta.source WHERE source_id = ANY(%s)",
        ([source["source_id"] for source in s0["sources"]],),
    ).fetchone()[0] == 0


def test_postgres_caller_can_roll_back_the_entire_load(connection, s0):
    from arsia_ingest.raw_load import load_prepared

    result = load_prepared(connection, s0["run_dir"], s0["sources"])
    assert result.inserted_count == 19
    connection.rollback()
    assert stored_rows(connection, s0) == []
    source_ids = [source["source_id"] for source in s0["sources"]]
    for table in ("meta.resource", "meta.source"):
        assert connection.execute(
            f"SELECT count(*) FROM {table} WHERE source_id = ANY(%s)", (source_ids,),
        ).fetchone()[0] == 0


def test_postgres_autocommit_connection_is_rejected(connection, s0):
    from arsia_ingest.raw_load import RawLoader

    connection.autocommit = True
    try:
        with pytest.raises(IntakeError) as error:
            RawLoader(connection, dataset_kind="synthetic", sources=s0["sources"],
                      files=s0["files"])
        assert error.value.code == "RAW_AUTOCOMMIT"
    finally:
        connection.autocommit = False


def test_postgres_file_and_parser_changes_create_distinct_raw_ids(connection, s0):
    from arsia_ingest.raw_load import RawLoader

    original = s0["rows"][0]
    loader = RawLoader(connection, dataset_kind="synthetic", sources=s0["sources"], files=s0["files"])
    loader.register()
    first = loader.load_record(original)
    assert first.inserted is True
    raw_ids = {first.raw_record_id}

    for field, value in (("file_sha256", "f" * 64),
                         ("parser_version", original["parser_version"] + "-revised")):
        files = deepcopy(s0["files"])
        selected = next(file for file in files if file["resource_id"] == original["resource_id"])
        selected[field] = value
        row = deepcopy(original)
        row[field] = value
        changed = RawLoader(connection, dataset_kind="synthetic", sources=s0["sources"], files=files)
        changed.register()

        accepted = changed.load_record(row)
        assert accepted.inserted is True
        assert accepted.raw_record_id not in raw_ids
        raw_ids.add(accepted.raw_record_id)
        repeated = changed.load_record(row)
        assert (repeated.raw_record_id, repeated.inserted) == (accepted.raw_record_id, False)
        assert connection.execute(
            "SELECT file_sha256, parser_version, row_locator, payload FROM raw.record "
            "WHERE raw_record_id = %s", (accepted.raw_record_id,),
        ).fetchone() == (row["file_sha256"], row["parser_version"],
                        original["row_locator"], original["payload"])

    assert len(raw_ids) == 3
    assert len(stored_rows(connection, s0)) == 3
    replay = loader.load_record(original)
    assert (replay.raw_record_id, replay.inserted) == (first.raw_record_id, False)
