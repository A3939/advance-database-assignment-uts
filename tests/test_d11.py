"""D11 three-report package integrity and result checks."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs/evidence/d11-s0-query-results-2026-09-28.json"
BATCH = "856bc5c6-a4f8-458d-8536-e9208de1ff84"


def load_receipt():
    return json.loads(RECEIPT.read_text(encoding="utf-8"))


def test_d11_one_successful_batch_and_required_totals():
    receipt = load_receipt()
    assert receipt["status"] == "passed"
    assert receipt["integration_commit"] == "562de2910bfd7be276b3036983e5680d436fde1e"
    assert receipt["batch"] == {
        "dataset_kind": "synthetic",
        "batch_id": BATCH,
        "status": "succeeded",
        "current_release": True,
        "input_fingerprint": "a0194382d567aa6df06bac97af3c2d228c1ff58e3b14d7468ffa54a19f31ee9d",
        "raw_rows": 19,
        "crashes": 6,
        "fatal_crashes": 2,
        "fatalities": 3,
        "casualties": 7,
        "map_points": 4,
    }
    assert all(
        row["batch_id"] == BATCH
        for section in (receipt["trend"]["annual_rows"], receipt["trend"]["monthly_rows"], receipt["severity"]["rows"], receipt["map"]["points"])
        for row in section
    )
    assert receipt["map"]["coverage"]["batch_id"] == BATCH


def test_d11_trend_preserves_coverage_unknowns_and_nulls():
    receipt = load_receipt()
    annual = receipt["trend"]["annual_rows"]
    monthly = receipt["trend"]["monthly_rows"]
    assert len(annual) == 15 and len(monthly) == 180
    assert sum(row["crash_count"] for row in annual) == 6
    assert sum((row["fatal_crash_count"] or 0) for row in annual) == 2
    assert sum((row["fatality_count"] or 0) for row in annual) == 3
    assert sum((row["casualty_count"] or 0) for row in annual) == 7
    assert sum(row["crash_count"] - row["month_known_count"] for row in annual) == 1
    empty = next(row for row in monthly if row["crash_count"] == 0)
    assert empty["coverage_status"] == "covered"
    assert empty["fatality_count"] is None and empty["casualty_count"] is None


def test_d11_severity_and_map_results_are_explicit():
    receipt = load_receipt()
    severity = receipt["severity"]["rows"]
    assert len(severity) == 6
    assert sum(row["crash_count"] for row in severity) == 6
    assert any(
        row["source_id"] == "syn_nsw" and row["severity_code"] == "__MISSING__"
        for row in severity
    )
    coverage = receipt["map"]["coverage"]
    assert (coverage["point_count"], coverage["crash_count"], coverage["coverage_percentage"]) == (4, 6, "66.67")
    assert len(receipt["map"]["points"]) == 4


def test_d11_environment_cleanup_and_inventory():
    receipt = load_receipt()
    assert receipt["environment"]["python"].startswith("3.12.")
    assert receipt["environment"]["psycopg"] == "3.3.6"
    assert receipt["environment"]["postgresql"].startswith("PostgreSQL 16.15 ")
    validation = receipt["validation"]
    assert (validation["tests"], validation["failures"], validation["errors"], validation["skipped"]) == (1, 0, 0, 0)
    assert validation["final_tables_empty"] is True
    assert validation["container_removed"] is True

    inventory = json.loads((ROOT / "config/d11-inventory.json").read_text(encoding="utf-8"))
    declared = {item["path"]: item["sha256"] for item in inventory["files"]}
    assert inventory["complete_d11"] is True
    assert set(declared) == set(inventory["components"]["reports_and_evidence"])
    for path, expected in declared.items():
        data = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == expected
