from pathlib import Path
import json

from arsia_ingest.publication import _required_objects


ROOT = Path(__file__).parents[1]

def test_e03_sql_declares_fp1_contract():
    sql = (ROOT / "sql/e/fp1.sql").read_text(encoding="utf-8")
    assert "CREATE OR REPLACE FUNCTION e.fp1(jsonb)" in sql
    assert "RETURNS text" in sql
    assert "digest($1::text, 'sha256')" in sql
    assert "GRANT EXECUTE ON FUNCTION e.fp1(jsonb) TO arsia_loader" in sql

def test_e04_expectations_match_s0_resource_counts():
    e = json.loads((ROOT / "config/e-independent-expectations.json").read_text())
    s0 = json.loads((ROOT / "tests/fixtures/s0/contract.json").read_text())
    expected = {r["resource_id"]: r["raw_count"] for r in s0["resources"]}
    actual = {k: v["raw_count"] for k, v in e["resources"].items()}
    assert actual == expected
    assert e["analysis"] == s0["analysis"]

def test_e06_requires_every_source_year():
    manifest = {
        "analysis": {"year_from": 2020, "year_to": 2022},
        "sources": [{"source_id": "syn_nsw"}, {"source_id": "syn_vic"}],
        "files": [
            {"resource_id": "syn_nsw_crash", "entity_kind": "crash", "file_sha256": "a" * 64, "parser_version": "p1"},
            {"resource_id": "syn_vic_accident", "entity_kind": "crash", "file_sha256": "b" * 64, "parser_version": "p1"},
        ],
    }
    objects = _required_objects(manifest)
    assert len(objects["QA06_RECONCILIATION"]) == 6
    assert "source_year:syn_nsw:2020" in objects["QA06_RECONCILIATION"]
    assert "source_year:syn_vic:2022" in objects["QA07_LOCATION"]

def test_e02_register_points_to_real_deliverables():
    register = (ROOT / "docs/e/e02-interface-register.md").read_text(encoding="utf-8")
    for path in ["sql/e/fp1.sql", "config/e-independent-expectations.json", "src/arsia_ingest/publication.py"]:
        assert path in register
