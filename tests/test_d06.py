"""D06 interface and deployment-contract tests without claiming PostgreSQL."""

import hashlib
import importlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from arsia_d06 import (
    QUERY_VERSION,
    SeverityRequest,
    install_sql,
    query_severity,
)
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
        "synthetic", BATCH, "syn_nsw", 2020, 2024, None,
        "s0-severity-v1", "__MISSING__", "Missing", "No native category", 1,
    )


def test_fixed_batch_query_binding_and_shape():
    connection = Connection((result_row(),))
    request = SeverityRequest(
        "synthetic", BATCH, source_ids=("syn_nsw",),
        year_from=2020, year_to=2024, months=(1, 2),
    )

    rows = query_severity(connection, request)

    assert rows[0]["batch_id"] == BATCH
    assert rows[0]["source_id"] == "syn_nsw"
    assert rows[0]["severity_code"] == "__MISSING__"
    assert rows[0]["crash_count"] == 1
    sql, parameters = connection.calls[0]
    assert "published.d06_severity" in sql
    assert parameters == (
        "synthetic", str(BATCH), ["syn_nsw"], 2020, 2024, [1, 2]
    )


@pytest.mark.parametrize(
    "case",
    [
        SeverityRequest("wrong", BATCH),
        SeverityRequest("synthetic", "not-a-uuid"),
        SeverityRequest("synthetic", BATCH, source_ids=()),
        SeverityRequest("synthetic", BATCH, source_ids="syn_nsw"),
        SeverityRequest("synthetic", BATCH, source_ids=("syn_nsw", "syn_nsw")),
        SeverityRequest("synthetic", BATCH, year_from=2024, year_to=2020),
        SeverityRequest("synthetic", BATCH, months=1),
        SeverityRequest("synthetic", BATCH, months=(0,)),
        SeverityRequest("synthetic", BATCH, months=(1, 1)),
    ],
)
def test_invalid_arguments_stop_before_query(case):
    connection = Connection()
    with pytest.raises(IntakeError) as error:
        query_severity(connection, case)
    assert error.value.code == "D06_ARGUMENT"
    assert connection.calls == []


def test_unexpected_database_shape_is_rejected():
    connection = Connection((("too", "short"),))
    with pytest.raises(IntakeError) as error:
        query_severity(connection, SeverityRequest("synthetic", BATCH))
    assert error.value.code == "D06_QUERY_SHAPE"


def test_deployment_sql_keeps_source_definitions_separate_and_read_only():
    sql = " ".join(install_sql().lower().split())
    assert QUERY_VERSION in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "candidate.status" in sql and "succeeded" in sql
    assert "candidate.dataset_kind" in sql
    assert "from dw.fact_crash as fact" in sql
    assert "join dw.dim_severity as severity" in sql
    assert "severity.source_id = fact.source_id" in sql
    assert "severity.severity_code = fact.severity_code" in sql
    assert "group by fact.source_id, severity.definition_version" in sql
    assert "fact.severity_code" in sql and "severity.severity_label" in sql
    assert "fact.month_id is not null" in sql
    assert "owner to arsia_migrator" in sql
    assert "to arsia_reader, arsia_loader" in sql
    assert "commit" not in sql and "rollback" not in sql
    assert "raw." not in sql and "canonical." not in sql


def test_sql_is_packaged_beside_module():
    path = Path(__file__).resolve().parents[1] / "src/arsia_d06/sql/d06_severity.sql"
    assert path.read_text(encoding="utf-8") == install_sql()


def test_d06_inventory_hashes_and_binding():
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads(
        (root / "config/d06-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["complete_d06"] is True
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
    assert callback is query_severity
