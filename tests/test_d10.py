"""D10 QLD model, query and evidence integrity checks."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence/d10-qld-source-query-2026-09-28.json"
SQL = ROOT / "sql/d10_qld_source_evidence.sql"


def test_d10_actual_results_reconcile_without_invented_units():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["scope"] == {
        "source_id": "official_qld",
        "resource_id": "official_qld_crash",
        "release_scope": "qld_pinned_2020_2024_v1",
        "file_sha256": "975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704",
        "analysis_year_from": 2020,
        "analysis_year_to": 2024,
        "source_grain": "one native row per crash",
        "native_key": ["Crash_Ref_Number"],
    }
    key = evidence["key_query"]
    assert key["full_source_rows"] == key["distinct_nonblank_keys"] == 415407
    assert key["blank_keys"] == key["duplicate_keys"] == 0
    assert key["analysis_rows"] == 66624
    month = evidence["month_query"]
    assert sum(month["rows_by_year"].values()) == 66624
    assert len(month["year_month_rows"]) == month["observed_year_months"] == 60
    assert sum(row["crash_count"] for row in month["year_month_rows"]) == 66624
    assert month["missing_or_unknown_month_rows"] == 0
    severity = evidence["severity_query"]
    assert sum(severity["counts"].values()) == 66624
    assert severity["missing_or_unknown_rows"] == 0
    unknown = evidence["unknown_count_query"]
    assert unknown == {
        "rows_with_missing_casualty_count": 0,
        "rows_with_invalid_casualty_count": 0,
        "rows_with_negative_casualty_count": 0,
        "casualty_component_mismatch_rows": 0,
        "fatality_sum": 1424,
        "casualty_total_sum": 88609,
    }
    units = evidence["unit_aggregate_query"]
    assert "no Unit entity" in units["handling"]
    assert units["rows_with_missing_unit_count"] == 0
    assert units["rows_with_invalid_unit_count"] == 0
    assert units["rows_with_negative_unit_count"] == 0
    published = evidence["published_build"]
    assert published["status"] == "succeeded"
    assert published["crash_count"] == 66624
    assert published["canonical_unit_count"] == 0
    assert published["report_eligible_unit_count"] == 0
    assert published["unit_rows"] is None


def test_d10_location_distinguishes_native_presence_from_map_eligibility():
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    location = evidence["location_query"]
    assert location["native_coordinate_rows"] == 66624
    assert location["blank_coordinate_rows"] == location["invalid_coordinate_rows"] == 0
    assert location["source_crs"] == "GDA2020"
    assert location["published_map_status"] == "unavailable"
    assert location["published_map_count"] == 0
    assert location["published_unmapped_count"] == 66624
    assert evidence["published_build"]["qa07"] == "limited"
    assert evidence["published_build"]["map_rows"] is None


def test_d10_sql_is_non_persistent_exactly_scoped_and_keeps_unit_counts_in_raw():
    sql = SQL.read_text(encoding="utf-8")
    lower = " ".join(sql.lower().split())
    assert "begin;" in lower and "rollback" in lower
    assert "create temporary view" in lower
    for forbidden in ("insert into", "update ", "delete from", "create table"):
        assert forbidden not in lower
    assert "source_id = 'official_qld'" in lower
    assert "resource_id = 'official_qld_crash'" in lower
    assert "975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704" in lower
    assert "crash_ref_number" in lower and "crash_year" in lower
    assert "property damage only" in lower and "__missing__" in lower
    for field in (
        "Count_Unit_Car", "Count_Unit_Motorcycle_Moped", "Count_Unit_Truck",
        "Count_Unit_Bus", "Count_Unit_Bicycle", "Count_Unit_Pedestrian",
        "Count_Unit_Other",
    ):
        assert f"payload ->> '{field}'" in sql
    assert "creates no Unit identity or relationship" in sql
    assert "from canonical.unit" in lower
    assert "d6f0e958-7c94-4f2f-ba85-9d44e597cc02" in lower


def test_d10_inventory_hashes_every_delivery_file():
    inventory = json.loads((ROOT / "config/d10-inventory.json").read_text(encoding="utf-8"))
    assert inventory["complete_d10"] is True
    assert inventory["final_presentation"] is False
    declared = {item["path"]: item["sha256"] for item in inventory["files"]}
    assert set(declared) == set(inventory["components"]["evidence"])
    for path, expected in declared.items():
        data = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(data).hexdigest()
        assert actual == expected, f"root={ROOT}; {path}: {actual} != {expected}; bytes={len(data)}"
