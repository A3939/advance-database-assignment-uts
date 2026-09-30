"""D07 interface and deployment-contract tests without claiming PostgreSQL."""

from decimal import Decimal
import hashlib
import importlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from arsia_d07 import MapRequest, QUERY_VERSION, install_sql, query_map
from arsia_ingest.models import IntakeError


BATCH = UUID("12345678-1234-5678-9234-567812345678")


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters):
        self.connection.calls.append((sql, parameters))
        self.rows = self.connection.results[len(self.connection.calls) - 1]

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def cursor(self):
        return Cursor(self)


def point(key="crash-1"):
    return (
        "synthetic", BATCH, "syn_nsw", "Synthetic NSW", "NSW",
        "s0-nsw-v1", key, 2020, 1, "F", Decimal("-33.1"), Decimal("151.2"),
    )


def coverage(crashes=1, points=1, percentage=Decimal("100.00")):
    return (
        "synthetic", BATCH, ["syn_nsw"], 2020, 2024, None,
        crashes, points, percentage,
    )


def test_fixed_batch_binding_shape_and_reconciliation():
    connection = Connection(((point(),), (coverage(),)))
    request = MapRequest(
        "synthetic", BATCH, source_ids=("syn_nsw",),
        year_from=2020, year_to=2024,
    )

    result = query_map(connection, request)

    assert result.points[0]["crash_key"] == "crash-1"
    assert result.points[0]["latitude"] == Decimal("-33.1")
    assert result.coverage["crash_count"] == 1
    assert result.coverage["point_count"] == 1
    assert result.coverage["coverage_percentage"] == Decimal("100.00")
    assert len(connection.calls) == 2
    assert "published.d07_map_points" in connection.calls[0][0]
    assert "published.d07_map_coverage" in connection.calls[1][0]
    assert connection.calls[0][1] == (
        "synthetic", str(BATCH), ["syn_nsw"], 2020, 2024, None
    )
    assert connection.calls[0][1] == connection.calls[1][1]


@pytest.mark.parametrize(
    "case",
    [
        MapRequest("wrong", BATCH),
        MapRequest("synthetic", "not-a-uuid"),
        MapRequest("synthetic", BATCH, source_ids=()),
        MapRequest("synthetic", BATCH, source_ids="syn_nsw"),
        MapRequest("synthetic", BATCH, source_ids=("syn_nsw", "syn_nsw")),
        MapRequest("synthetic", BATCH, year_from=2024, year_to=2020),
        MapRequest("synthetic", BATCH, months=1),
        MapRequest("synthetic", BATCH, months=(0,)),
        MapRequest("synthetic", BATCH, months=(1, 1)),
    ],
)
def test_invalid_arguments_stop_before_query(case):
    connection = Connection(())
    with pytest.raises(IntakeError) as error:
        query_map(connection, case)
    assert error.value.code == "D07_ARGUMENT"
    assert connection.calls == []


def test_point_shape_is_rejected():
    connection = Connection((("too", "short"), (coverage(),)))
    with pytest.raises(IntakeError) as error:
        query_map(connection, MapRequest("synthetic", BATCH))
    assert error.value.code == "D07_POINT_SHAPE"


def test_coverage_shape_and_point_count_are_rejected():
    missing = Connection(((point(),), ()))
    with pytest.raises(IntakeError) as error:
        query_map(missing, MapRequest("synthetic", BATCH))
    assert error.value.code == "D07_COVERAGE_SHAPE"

    mismatch = Connection(((point(),), (coverage(points=2),)))
    with pytest.raises(IntakeError) as error:
        query_map(mismatch, MapRequest("synthetic", BATCH))
    assert error.value.code == "D07_RECONCILIATION"


def test_sql_preserves_identity_and_calculates_coverage_in_database():
    sql = " ".join(install_sql().lower().split())
    assert QUERY_VERSION in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "candidate.status" in sql and "succeeded" in sql
    assert "from published.d07_validate_request" in sql
    assert "join dw.fact_crash as fact" in sql
    assert "fact.map_eligible" in sql
    assert "fact.latitude is not null" in sql
    assert "fact.longitude is not null" in sql
    assert "fact.source_id, fact.release_scope, fact.crash_key" in sql
    assert "count(fact.crash_key)" in sql
    assert "100.0 * count" in sql and "round(" in sql
    assert "when count(fact.crash_key) = 0 then null" in sql
    assert "owner to arsia_migrator" in sql
    assert "to arsia_reader, arsia_loader" in sql
    assert "commit" not in sql and "rollback" not in sql
    assert "raw." not in sql and "canonical." not in sql
    assert "canonical.unit" not in sql


def test_sql_is_packaged_beside_module():
    path = Path(__file__).resolve().parents[1] / "src/arsia_d07/sql/d07_map.sql"
    assert path.read_text(encoding="utf-8") == install_sql()


def test_d07_inventory_hashes_and_binding():
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads(
        (root / "config/d07-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["complete_d07"] is True
    assert inventory["complete_analysis"] is False
    declared = {item["path"]: item["sha256"] for item in inventory["code_files"]}
    assert set(declared) == set(inventory["components"]["analysis"])
    for path, expected in declared.items():
        data = (root / path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == expected
    module_name, callback_name = inventory["binding"]["python"].split(":")
    callback = getattr(importlib.import_module(module_name), callback_name)
    assert callback is query_map
