"""D04 QA06 contract tests without claiming PostgreSQL execution."""

import hashlib
import importlib
import json
from pathlib import Path

import pytest

from arsia_d04 import RULE_ID, reconcile
from arsia_d04.reconciliation import DETAIL_SQL, METRICS_SQL, METRIC_NAMES
from arsia_ingest.models import IntakeError
from arsia_ingest.runner import RunEvidence


BATCH = "12345678-1234-5678-9234-567812345678"
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = {
    "analysis": {"year_from": 2020, "year_to": 2020},
    "sources": [{"source_id": "syn_nsw"}],
    "files": [{
        "source_id": "syn_nsw",
        "resource_id": "syn_nsw_crash",
        "entity_kind": "crash",
        "file_sha256": "a" * 64,
        "parser_version": "xlsx-native-v1",
    }],
}


def metric_row(*, metrics=None, evaluated=2, expected=2, affected=0):
    values = dict.fromkeys(METRIC_NAMES, 0)
    values.update(metrics or {})
    return (evaluated, expected, *(values[name] for name in METRIC_NAMES), affected)


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []
        self.position = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters):
        self.connection.executed.append((sql, parameters))
        if "pair_totals AS" in sql:
            self.rows = [self.connection.metrics]
        elif "to_jsonb(canonical_row)" in sql:
            self.rows = list(self.connection.details)
        else:
            raise AssertionError("unexpected SQL")
        self.position = 0
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchmany(self, size):
        rows = self.rows[self.position:self.position + size]
        self.position += len(rows)
        return rows


class Connection:
    def __init__(self, metrics=None, details=()):
        self.metrics = metrics or metric_row()
        self.details = details
        self.executed = []

    def cursor(self):
        return Cursor(self)


def test_pass_result_and_batch_summary_cover_source_year():
    report = reconcile(Connection(), BATCH, MANIFEST)
    row, summary = report.rows

    assert row["rule_id"] == RULE_ID
    assert row["object_key"] == "source_year:syn_nsw:2020"
    assert row["result"] == "pass" and row["affected_count"] == 0
    assert row["actual"] == {
        "evaluated_count": 2,
        "violation_count": 0,
        "metrics": dict.fromkeys(METRIC_NAMES, 0),
    }
    assert row["expected"]["evaluated_count"] == 2
    assert summary["object_key"] == "batch"
    assert summary["result"] == "pass"
    assert summary["actual"]["metrics"] == {
        "object_count": 1,
        "pass_count": 1,
        "limited_count": 0,
        "block_count": 0,
        "missing_count": 0,
    }


def test_zero_crash_year_is_still_a_passing_object():
    report = reconcile(
        Connection(metrics=metric_row(evaluated=0, expected=0)),
        BATCH,
        MANIFEST,
    )
    assert report.rows[0]["actual"]["evaluated_count"] == 0
    assert report.rows[0]["expected"]["evaluated_count"] == 0
    assert report.rows[0]["result"] == "pass"


def test_key_and_field_differences_block_with_located_evidence(tmp_path):
    canonical = {
        "raw_record_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "severity_code": "F",
    }
    fact = {"severity_code": "I"}
    detail = (
        "syn-2020", '["0001"]', False, False, True, False, False,
        canonical, fact,
        "syn_nsw_crash", "a" * 64, "xlsx-native-v1", "sheet:Crash!row:2",
        None, None, None, None,
    )
    connection = Connection(
        metrics=metric_row(
            metrics={"field_mismatch_count": 1}, affected=1
        ),
        details=(detail,),
    )
    evidence = RunEvidence(tmp_path / "qa_d")
    report = reconcile(connection, BATCH, MANIFEST, evidence=evidence)
    row, summary = report.rows

    assert row["result"] == "block" and row["affected_count"] == 1
    assert row["evidence"]["reason_codes"] == ["FIELD_MISMATCH"]
    reference = row["evidence"]["references"][1]
    assert reference["row_count"] == 1
    path = Path(reference["path"])
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert '"crash_key": "[\\"0001\\"]"' in text
    assert '"row_locator": "sheet:Crash!row:2"' in text
    assert row["raw_record_id"] == canonical["raw_record_id"]
    assert summary["result"] == "block"
    assert summary["affected_count"] == 1


def test_incomplete_difference_evidence_is_rejected(tmp_path):
    connection = Connection(
        metrics=metric_row(
            metrics={"missing_fact_count": 1, "crash_delta": -1},
            evaluated=1,
            expected=1,
            affected=1,
        ),
        details=(),
    )
    with pytest.raises(IntakeError) as error:
        reconcile(
            connection,
            BATCH,
            MANIFEST,
            evidence=RunEvidence(tmp_path / "qa_d"),
        )
    assert error.value.code == "D04_DETAIL_COUNT"


def test_sql_uses_full_identity_null_safe_fields_and_no_units():
    sql = " ".join(METRICS_SQL.lower().split())
    for field in ("batch_id", "source_id", "release_scope", "crash_key"):
        assert f"fact_rows.{field} = canonical_rows.{field}" in sql
    assert "is distinct from" in sql
    assert "raw.record" in sql
    assert "allowed_lineage" in sql
    assert "file_sha256 = primary_raw.file_sha256" in sql
    assert "severity_definition_version" in sql
    assert "canonical.unit" not in sql
    assert "dw.fact_unit" not in sql
    assert "to_jsonb(canonical_row)" in DETAIL_SQL


def test_frozen_manifest_lineage_identities_are_bound_to_query():
    connection = Connection()
    reconcile(connection, BATCH, MANIFEST)

    allowed = json.loads(connection.executed[0][1][0])
    assert allowed == [
        {
            "lineage_kind": "primary",
            "resource_id": "syn_nsw_crash",
            "file_sha256": "a" * 64,
            "parser_version": "xlsx-native-v1",
        },
        {
            "lineage_kind": "location",
            "resource_id": "syn_nsw_crash",
            "file_sha256": "a" * 64,
            "parser_version": "xlsx-native-v1",
        },
    ]


@pytest.mark.parametrize(
    "manifest,code",
    [
        ({}, "D04_MANIFEST"),
        ({"sources": [], "analysis": {"year_from": 2020, "year_to": 2020}},
         "D04_MANIFEST"),
        ({"sources": [{"source_id": "x"}],
          "analysis": {"year_from": 2021, "year_to": 2020}}, "D04_MANIFEST"),
    ],
)
def test_invalid_scope_is_rejected_before_query(manifest, code):
    connection = Connection()
    with pytest.raises(IntakeError) as error:
        reconcile(connection, BATCH, manifest)
    assert error.value.code == code
    assert connection.executed == []


def test_invalid_batch_is_rejected_before_query():
    connection = Connection()
    with pytest.raises(IntakeError) as error:
        reconcile(connection, "not-a-uuid", MANIFEST)
    assert error.value.code == "D04_BATCH_ID"
    assert connection.executed == []


def test_qa06_inventory_hashes_and_binding():
    inventory = json.loads(
        (ROOT / "config/d04-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["complete_qa06"] is True
    assert inventory["final_platform"] is False
    assert set(inventory["components"]) == {"qa"}
    declared = {
        entry["path"]: entry["sha256"] for entry in inventory["code_files"]
    }
    assert set(declared) == set(inventory["components"]["qa"])
    for path, expected in declared.items():
        data = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == expected

    module_name, callback_name = inventory["binding"]["callback"].split(":")
    callback = getattr(importlib.import_module(module_name), callback_name)
    assert callback is importlib.import_module("arsia_d04").runner_callback
    assert inventory["binding"]["code_path"] in inventory["components"]["qa"]
