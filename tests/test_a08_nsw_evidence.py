import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/sources/evidence/nsw/a08-nsw-query-results-2026-09-26.json"
SQL = ROOT / "sql/evidence/a08_nsw_source_queries.sql"
CONFIG = ROOT / "config/a08-official-nsw-input.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def queries(evidence):
    return {query["name"]: query for query in evidence["queries"]}


def test_a08_evidence_is_bound_to_selected_inputs_and_sql():
    evidence = load(EVIDENCE)
    config = load(CONFIG)
    files = {item["resource_id"]: item for item in evidence["prepared_run"]["files"]}

    assert evidence["prepared_run"]["status"] == "prepared"
    assert evidence["prepared_run"]["raw_count"] == 263151
    assert evidence["load"] == {
        "run_id": evidence["prepared_run"]["run_id"],
        "dataset_kind": "official",
        "raw_count": 263151,
        "inserted_count": 263151,
        "reused_count": 0,
    }
    assert {item["resource_id"] for item in config["resources"]} == set(files)
    for item in config["resources"]:
        prepared = files[item["resource_id"]]
        assert prepared["file_sha256"] == item["expected_sha256"]
        assert prepared["header"] == item["header"]
        assert prepared["sheet"] == item["sheet"]

    assert evidence["sql"]["sha256"] == hashlib.sha256(SQL.read_bytes()).hexdigest()


def test_a08_results_preserve_native_keys_relationships_and_scope():
    result = queries(load(EVIDENCE))

    assert result["source_counts"]["rows"] == [
        ["Crash", 92189, 92189, 0],
        ["Traffic Unit", 170962, 170962, 0],
    ]
    assert result["key_and_parent_quality"]["rows"] == [[0, 0, 0, 0, 0]]
    assert result["reporting_occurrence_year_differences"]["rows"] == [
        [92189, 488]
    ]
    assert result["declared_unit_reconciliation"]["rows"] == [
        [92189, 0, 0, 170962, 170962]
    ]
    assert result["analysis_scope"]["rows"] == [
        [92082, 170747, 107, 215, 60]
    ]

    examples = result["relationship_examples"]["rows"]
    assert len(examples) == 10
    for crash_id, crash_key, unit_id, unit_key, unit_type in examples:
        assert json.loads(crash_key) == [crash_id]
        assert json.loads(unit_key) == [crash_id, unit_id]
        assert unit_type


def test_a08_run_used_restricted_postgres_and_restored_baseline():
    evidence = load(EVIDENCE)

    assert evidence["database"]["postgresql_major"] == 16
    assert evidence["database"]["current_user"] == "arsia_loader"
    assert evidence["database"]["server_encoding"] == "UTF8"
    assert evidence["database"]["timezone"] == "UTC"
    assert evidence["database"]["superuser"] is False
    assert evidence["rollback"] == {
        "baseline": {"source_rows": 0, "resource_rows": 0, "raw_rows": 0},
        "performed": True,
        "after": {"source_rows": 0, "resource_rows": 0, "raw_rows": 0},
        "restored": True,
    }
