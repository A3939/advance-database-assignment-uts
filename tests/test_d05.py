"""D05 interface and deployment-contract tests without claiming PostgreSQL."""

import hashlib
import importlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from arsia_d05 import QUERY_VERSION, TrendRequest, install_sql, query_trend
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


def result_row():
    return (
        "synthetic", BATCH, "syn_nsw", "year", 2020, None,
        "covered", 12, 12, "S0 coverage", 2, 1, 0,
        1, 2, 1, 2, 3, 2,
    )


def test_fixed_batch_query_binding_and_shape():
    connection = Connection((result_row(),))
    request = TrendRequest(
        "synthetic", BATCH, source_ids=("syn_nsw",),
        year_from=2020, year_to=2024, months=(1, 2),
    )

    rows = query_trend(connection, request)

    assert rows[0]["batch_id"] == BATCH
    assert rows[0]["crash_count"] == 2
    assert rows[0]["fatal_crash_count"] == 1
    sql, parameters = connection.calls[0]
    assert "published.d05_trend" in sql
    assert parameters == (
        "synthetic", str(BATCH), "year", ["syn_nsw"],
        2020, 2024, [1, 2],
    )


@pytest.mark.parametrize(
    "case",
    [
        TrendRequest("wrong", BATCH),
        TrendRequest("synthetic", "not-a-uuid"),
        TrendRequest("synthetic", BATCH, grain="day"),
        TrendRequest("synthetic", BATCH, source_ids=()),
        TrendRequest("synthetic", BATCH, source_ids="syn_nsw"),
        TrendRequest("synthetic", BATCH, source_ids=("syn_nsw", "syn_nsw")),
        TrendRequest("synthetic", BATCH, year_from=2024, year_to=2020),
        TrendRequest("synthetic", BATCH, months=(0,)),
        TrendRequest("synthetic", BATCH, months=1),
        TrendRequest("synthetic", BATCH, months=(1, 1)),
    ],
)
def test_invalid_arguments_stop_before_query(case):
    connection = Connection()
    with pytest.raises(IntakeError) as error:
        query_trend(connection, case)
    assert error.value.code == "D05_ARGUMENT"
    assert connection.calls == []


def test_unexpected_database_shape_is_rejected():
    connection = Connection((("too", "short"),))
    with pytest.raises(IntakeError) as error:
        query_trend(connection, TrendRequest("synthetic", BATCH))
    assert error.value.code == "D05_QUERY_SHAPE"


def test_deployment_sql_enforces_l5_semantics_and_reader_boundary():
    sql = " ".join(install_sql().lower().split())
    assert QUERY_VERSION in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "candidate.status" in sql and "succeeded" in sql
    assert "candidate.dataset_kind" in sql
    assert "jsonb_array_elements" in sql and "rules,contracts" in sql
    assert "content,input,entity_kind" in sql
    assert "dw.fact_crash" in sql
    assert "count(fact.batch_id)" in sql
    assert "fact.month_id is not null" in sql
    assert "fact.month_id % 100" in sql
    assert "fatal_crash_eligible" in sql
    assert "fatality_eligible" in sql
    assert "casualty_eligible" in sql
    assert "not_covered" in sql and "partial" in sql and "covered" in sql
    assert "to arsia_reader, arsia_loader" in sql
    assert "owner to arsia_migrator" in sql
    assert "commit" not in sql and "rollback" not in sql
    assert "raw." not in sql and "canonical." not in sql


def test_sql_is_packaged_beside_module():
    path = Path(__file__).resolve().parents[1] / "src/arsia_d05/sql/d05_trend.sql"
    assert path.read_text(encoding="utf-8") == install_sql()


def test_d05_inventory_hashes_and_binding():
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads(
        (root / "config/d05-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["complete_d05"] is True
    assert inventory["complete_analysis"] is False
    declared = {
        item["path"]: item["sha256"] for item in inventory["code_files"]
    }
    assert set(declared) == set(inventory["components"]["analysis"])
    for path, expected in declared.items():
        data = (root / path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == expected
    module_name, callback_name = inventory["binding"]["python"].split(":")
    callback = getattr(importlib.import_module(module_name), callback_name)
    assert callback is query_trend
