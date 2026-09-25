"""C07 SQL and numeric output on an isolated, migrated PostgreSQL 16 database."""

import csv
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

from arsia_c.node_location import (
    NodeObservation, iter_node_observation_groups, resolve_location_update,
)

pytestmark = pytest.mark.skipif(
    "C07_TEST_DSN" not in os.environ,
    reason="Set C07_TEST_DSN to an isolated A database as arsia_loader",
)


@pytest.fixture
def connection():
    import psycopg

    assert os.environ["C07_TEST_DSN"], "C07_TEST_DSN must not be empty"
    with psycopg.connect(os.environ["C07_TEST_DSN"], connect_timeout=10) as conn:
        try:
            assert conn.info.server_version // 10000 == 16
            assert conn.execute(
                "SELECT current_user, rolsuper FROM pg_roles WHERE rolname=current_user"
            ).fetchone() == ("arsia_loader", False)
            assert conn.execute(
                "SELECT has_table_privilege(current_user, 'raw.record', 'UPDATE'),"
                " has_table_privilege(current_user, 'raw.record', 'DELETE')"
            ).fetchone() == (False, False)
            yield conn
        finally:
            conn.rollback()


@pytest.mark.parametrize("latitude,longitude", [
    ("-37.80000001", "144.90000001"),
    ("-37.80000005", "144.90000005"),
    ("37.80000005", "-144.90000005"),
    ("89.99999999", "179.99999999"),
])
def test_rounding_matches_postgres(connection, latitude, longitude):
    obs = NodeObservation(
        str(uuid4()), "A1", "N1", latitude, longitude, "a" * 64, "csv-v1", "csv:1",
    )
    update = resolve_location_update(
        [obs], expected_accident_no="A1", expected_node_id="N1",
        crs_confirmed=True, evidence_ref="synthetic:c07-postgres",
    )
    stored = connection.execute(
        "SELECT %s::numeric(10,7), %s::numeric(10,7)", (latitude, longitude),
    ).fetchone()
    assert (update["latitude"], update["longitude"]) == stored


def test_s0_raw_query_and_caller_rollback(connection):
    from psycopg.types.json import Jsonb

    source_id = "syn_c07_" + uuid4().hex
    resource_id = source_id + "_node"
    connection.execute("INSERT INTO meta.source VALUES (%s, 'VIC', 'C07 test', 'test')",
                       (source_id,))
    connection.execute("INSERT INTO meta.resource VALUES (%s, %s, 'node', 'node_raw')",
                       (resource_id, source_id))
    path = Path(__file__).parent / "fixtures/s0/syn_vic_node.csv"
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    insert = """INSERT INTO raw.record
        (raw_record_id, resource_id, source_id, file_sha256,
         parser_version, row_locator, payload) VALUES (%s,%s,%s,%s,%s,%s,%s)"""
    ids = []
    for index, row in enumerate(rows, 1):
        raw_id = uuid4()
        ids.append(str(raw_id))
        connection.execute(insert, (
            raw_id, resource_id, source_id, file_hash, "csv-native-v1",
            f"csv:{index}", Jsonb(row),
        ))
    for sha, parser in [("b" * 64, "csv-native-v1"), (file_hash, "other-parser")]:
        connection.execute(insert, (
            uuid4(), resource_id, source_id, sha, parser, "csv:1", Jsonb(rows[0]),
        ))
    groups = list(iter_node_observation_groups(connection, {
        "source_id": source_id, "resource_id": resource_id,
        "file_sha256": file_hash, "parser_version": "csv-native-v1",
    }))
    assert [(key, len(group)) for key, group in groups] == [
        (("0001", "NODE01"), 2), (("0002", "NODE02"), 2),
    ]
    assert [row.raw_record_id for _, group in groups for row in group] == ids
    for index, ((accident_no, node_id), group) in enumerate(groups):
        update = resolve_location_update(
            group, expected_accident_no=accident_no, expected_node_id=node_id,
            crs_confirmed=True, evidence_ref="synthetic:c07-postgres",
        )
        assert update["map_eligible"] is (index == 0)
    assert connection.execute(
        "SELECT count(*) FROM raw.record WHERE source_id=%s", (source_id,),
    ).fetchone() == (6,)
    connection.rollback()
    assert connection.execute(
        "SELECT count(*) FROM meta.source WHERE source_id=%s", (source_id,),
    ).fetchone() == (0,)
