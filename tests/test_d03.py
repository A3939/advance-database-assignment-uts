"""D03 contract tests that do not claim PostgreSQL execution."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from arsia_d03 import FactContractError, load_facts
from arsia_d03.facts import FACT_INSERT_SQL


BATCH = "12345678-1234-5678-9234-567812345678"
ROOT = Path(__file__).resolve().parents[1]


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters):
        self.connection.executed.append((sql, parameters))
        if "LEFT JOIN dw.dim_source AS source" in sql:
            self.rows = [self.connection.preflight]
        elif "differences AS" in sql:
            self.rows = [self.connection.verification]
        elif "GROUP BY source_id" in sql:
            self.rows = list(self.connection.sources)
        elif "INSERT INTO dw.fact_crash" in sql:
            self.rows = []
            self.rowcount = self.connection.inserted
        else:
            raise AssertionError("unexpected SQL")
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class Connection:
    def __init__(
        self,
        *,
        preflight=(0, 0, 0, 0, 0),
        verification=(2, 2, 0),
        inserted=2,
        sources=(("syn_nsw", 2),),
    ):
        self.preflight = preflight
        self.verification = verification
        self.inserted = inserted
        self.sources = sources
        self.executed = []

    def cursor(self):
        return Cursor(self)


def test_load_facts_reconciles_exact_canonical_set():
    connection = Connection()
    result = load_facts(connection, BATCH)

    assert result.counts() == {"fact_crash": 2}
    assert result.inserted_count == 2
    assert result.source_counts == {"syn_nsw": 2}
    assert len(connection.executed) == 4


def test_repeated_load_may_reuse_exact_existing_facts():
    result = load_facts(Connection(inserted=0), BATCH)
    assert result.fact_count == 2
    assert result.inserted_count == 0


@pytest.mark.parametrize(
    "preflight,field",
    [
        ((1, 0, 0, 0, 0), "missing_source"),
        ((0, 1, 0, 0, 0), "release_scope_mismatch"),
        ((0, 0, 1, 0, 0), "missing_severity"),
        ((0, 0, 0, 1, 0), "severity_definition_mismatch"),
        ((0, 0, 0, 0, 1), "missing_month"),
    ],
)
def test_dimension_contract_mismatch_blocks_before_insert(preflight, field):
    connection = Connection(preflight=preflight)
    with pytest.raises(FactContractError) as error:
        load_facts(connection, BATCH)
    assert error.value.code == "D03_DIMENSION_CONTRACT"
    assert error.value.details["failures"] == {field: 1}
    assert all("INSERT INTO dw.fact_crash" not in sql for sql, _ in connection.executed)


@pytest.mark.parametrize("verification", [(2, 1, 1), (2, 2, 1), (1, 2, 1)])
def test_missing_extra_or_changed_fact_is_rejected(verification):
    with pytest.raises(FactContractError) as error:
        load_facts(Connection(verification=verification), BATCH)
    assert error.value.code == "D03_DATABASE_MISMATCH"


def test_invalid_batch_is_rejected_before_query():
    connection = Connection()
    with pytest.raises(FactContractError) as error:
        load_facts(connection, "not-a-uuid")
    assert error.value.code == "D03_BATCH_ID"
    assert connection.executed == []


def test_fact_insert_never_reads_or_joins_units():
    sql = " ".join(FACT_INSERT_SQL.lower().split())
    assert "from canonical.crash" in sql
    assert "canonical.unit" not in sql
    assert " join " not in sql
    assert "occurrence_year * 100 + occurrence_month" in sql


def test_complete_dw_inventory_hashes_and_combined_binding():
    inventory = json.loads(
        (ROOT / "config/d03-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["complete_dw"] is True
    assert set(inventory["components"]) == {"dw"}
    declared = {
        entry["path"]: entry["sha256"] for entry in inventory["code_files"]
    }
    assert set(declared) == set(inventory["components"]["dw"])
    for path, expected in declared.items():
        # Git stores these text files with LF.  Normalise a Windows checkout's
        # CRLF so the inventory validates the same committed bytes everywhere.
        data = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(data).hexdigest()
        assert actual == expected

    module_name, callback_name = inventory["binding"]["callback"].split(":")
    callback = getattr(importlib.import_module(module_name), callback_name)
    assert callback is importlib.import_module("arsia_d03").runner_callback
    assert inventory["binding"]["code_path"] in inventory["components"]["dw"]
