"""D08 interface and deployment-contract tests without claiming PostgreSQL."""

import hashlib
import importlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from arsia_d08 import QUERY_VERSION, UnitRequest, install_sql, query_units
from arsia_ingest.models import IntakeError


BATCH = UUID("12345678-1234-5678-9234-567812345678")


class Cursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters):
        self.connection.calls.append((sql, parameters))

    def fetchall(self):
        return self.connection.rows


class Connection:
    def __init__(self, rows=()):
        self.rows = rows
        self.calls = []

    def cursor(self):
        return Cursor(self)


def unit_row(count=3):
    return (
        "synthetic",
        BATCH,
        "syn_nsw",
        "Synthetic NSW",
        "NSW",
        "synthetic_traffic_unit",
        "CAR",
        count,
    )


def test_fixed_batch_binding_and_result_shape():
    connection = Connection((unit_row(),))
    request = UnitRequest(
        "synthetic",
        BATCH,
        source_ids=("syn_nsw",),
        year_from=2020,
        year_to=2024,
        months=(1, 2),
    )

    result = query_units(connection, request)

    assert result == (
        {
            "dataset_kind": "synthetic",
            "batch_id": BATCH,
            "source_id": "syn_nsw",
            "source_name": "Synthetic NSW",
            "jurisdiction_code": "NSW",
            "statistical_scope": "synthetic_traffic_unit",
            "unit_type_code": "CAR",
            "unit_count": 3,
        },
    )
    assert len(connection.calls) == 1
    assert "published.d08_unit_counts" in connection.calls[0][0]
    assert connection.calls[0][1] == (
        "synthetic", str(BATCH), ["syn_nsw"], 2020, 2024, [1, 2]
    )


@pytest.mark.parametrize(
    "case",
    [
        UnitRequest("wrong", BATCH),
        UnitRequest("synthetic", "not-a-uuid"),
        UnitRequest("synthetic", BATCH, source_ids=()),
        UnitRequest("synthetic", BATCH, source_ids="syn_nsw"),
        UnitRequest("synthetic", BATCH, source_ids=("syn_nsw", "syn_nsw")),
        UnitRequest("synthetic", BATCH, year_from=True),
        UnitRequest("synthetic", BATCH, year_from=2024, year_to=2020),
        UnitRequest("synthetic", BATCH, months=1),
        UnitRequest("synthetic", BATCH, months=(0,)),
        UnitRequest("synthetic", BATCH, months=(1, 1)),
    ],
)
def test_invalid_arguments_stop_before_query(case):
    connection = Connection()
    with pytest.raises(IntakeError) as error:
        query_units(connection, case)
    assert error.value.code == "D08_ARGUMENT"
    assert connection.calls == []


@pytest.mark.parametrize("row", [("too", "short"), unit_row(0), unit_row(-1)])
def test_invalid_result_shape_is_rejected(row):
    connection = Connection((row,))
    with pytest.raises(IntakeError) as error:
        query_units(connection, UnitRequest("synthetic", BATCH))
    assert error.value.code == "D08_RESULT_SHAPE"


def test_empty_result_is_valid():
    assert query_units(Connection(), UnitRequest("synthetic", BATCH)) == ()


def test_sql_uses_complete_parent_identity_and_only_eligible_units():
    sql = " ".join(install_sql().lower().split())
    assert QUERY_VERSION in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "candidate.status" in sql and "succeeded" in sql
    assert "from canonical.unit as unit" in sql
    assert "unit.count_eligible" in sql
    assert "join dw.fact_crash as parent" in sql
    for equality in (
        "parent.batch_id = unit.batch_id",
        "parent.source_id = unit.source_id",
        "parent.release_scope = unit.release_scope",
        "parent.crash_key = unit.crash_key",
    ):
        assert equality in sql
    assert "group by unit.source_id" in sql
    assert "unit.statistical_scope" in sql
    assert "unit.unit_type_code" in sql
    assert "count(*)::bigint" in sql
    assert "sum(parent." not in sql
    assert "raw." not in sql and "rv." not in sql
    assert "owner to arsia_migrator" in sql
    assert "to arsia_reader, arsia_loader" in sql
    assert "commit" not in sql and "rollback" not in sql


def test_sql_is_packaged_beside_module():
    path = Path(__file__).resolve().parents[1] / "src/arsia_d08/sql/d08_units.sql"
    assert path.read_text(encoding="utf-8") == install_sql()


def test_d08_inventory_hashes_and_binding():
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads(
        (root / "config/d08-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["complete_d08"] is True
    assert inventory["complete_analysis"] is False
    declared = {item["path"]: item["sha256"] for item in inventory["code_files"]}
    assert set(declared) == set(inventory["components"]["analysis"])
    for path, expected in declared.items():
        data = (root / path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == expected
    module_name, callback_name = inventory["binding"]["python"].split(":")
    callback = getattr(importlib.import_module(module_name), callback_name)
    assert callback is query_units
