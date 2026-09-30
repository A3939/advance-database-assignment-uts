"""B's S8 extension to C10: derive expectations from native values, not SQL output."""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from arsia_c import qa
from arsia_c.qa_expectations import Source
from arsia_ingest.manifest import s0_definitions

ROOT = Path(__file__).resolve().parents[1]
RAW_ID = "00000000-0000-0000-0000-000000000008"
BATCH = "00000000-0000-0000-0000-000000000001"
PAYLOAD = {
    "CRASH_ID": "0001", "YEAR": "2020", "MONTH": "01", "SEVERITY": "F",
    "FATALITIES": "1", "CASUALTIES": "1", "LATITUDE": "-34.92", "LONGITUDE": "138.60",
}


@pytest.fixture
def inputs():
    definitions = s0_definitions(ROOT / "tests/fixtures/s8/contract.json")
    # These unit tests exercise Raw derivation; the PostgreSQL suite uses FrozenManifest.
    manifest = {
        "dataset_kind": "synthetic", "analysis": definitions["analysis"],
        "sources": definitions["sources"],
        "files": [c["content"]["input"] for c in definitions["contracts"]],
        "rules": {k: definitions[k] for k in ("contracts", "mappings", "severity")},
    }
    source = next(s for s in manifest["sources"] if s["source_id"] == "syn_sa")
    row = {"raw_record_id": RAW_ID, "resource_id": "syn_sa_crash",
           "row_locator": "csv:1", "payload": deepcopy(PAYLOAD)}
    return manifest, source, {"syn_sa_crash": [row]}


def derive(inputs, **patch):
    manifest, source, raw = deepcopy(inputs)
    raw["syn_sa_crash"][0]["payload"].update(patch)
    return Source(manifest, source, raw, BATCH)


def test_sa_raw_expectations_keep_native_identity_and_direct_casualty_total(inputs):
    source = derive(inputs)
    assert not source.errors and not source.coverage
    assert set(source.by_role) == {"crash"}
    row, = source.projected["syn_sa_crash"]
    assert row["crash_key"] == '["0001"]'
    assert (row["occurrence_year"], row["occurrence_month"], row["occurrence_date"],
            row["date_precision"]) == (2020, 1, None, "month")
    assert (row["fatality_count"], row["casualty_count"]) == (1, 1)
    assert row["severity_code"] == "F" and row["is_fatal_crash"] is True
    assert all(row[k] is True for k in ("fatal_crash_eligible", "fatality_eligible", "casualty_eligible", "map_eligible"))
    assert (row["latitude"], row["longitude"], row["location_crs"]) == (
        Decimal("-34.9200000"), Decimal("138.6000000"), "EPSG:4326")
    assert row["location_record_id"] == row["raw_record_id"] == RAW_ID


@pytest.mark.parametrize("severity,fatal", [("F", True), ("I", False), ("N", False), ("", None), (None, None)])
def test_sa_severity_is_source_defined_and_missing_stays_unknown(inputs, severity, fatal):
    source = derive(inputs, SEVERITY=severity)
    row, = source.projected["syn_sa_crash"]
    assert row["is_fatal_crash"] is fatal
    assert row["fatal_crash_eligible"] is (fatal is not None)
    assert row["severity_code"] == (severity or "__MISSING__")


@pytest.mark.parametrize("fatalities,casualties,expected", [
    ("", "3", (None, 3)), ("2", "", (2, None)), (None, None, (None, None)),
    ("0", "0", (0, 0)), ("2147483647", "2147483647", (2147483647, 2147483647)),
])
def test_sa_counts_do_not_sum_deaths_twice_or_replace_unknown_with_zero(inputs, fatalities, casualties, expected):
    source = derive(inputs, FATALITIES=fatalities, CASUALTIES=casualties)
    row, = source.projected["syn_sa_crash"]
    assert (row["fatality_count"], row["casualty_count"]) == expected
    assert row["fatality_eligible"] is (expected[0] is not None)
    assert row["casualty_eligible"] is (expected[1] is not None)


@pytest.mark.parametrize("patch,reason", [
    ({"CRASH_ID": "   "}, "blank_key"),
    ({"MONTH": "January"}, "invalid_month"), ({"MONTH": ""}, "invalid_month"),
    ({"MONTH": "13"}, "invalid_month"), ({"YEAR": "0000"}, "invalid_year"),
    ({"YEAR": "1899"}, "invalid_year"), ({"YEAR": "2101"}, "invalid_year"),
    ({"SEVERITY": "Unknown"}, "undefined_category"),
    ({"FATALITIES": "-1"}, "invalid_count"), ({"CASUALTIES": "1.0"}, "invalid_count"),
    ({"CASUALTIES": "2147483648"}, "invalid_count"),
    ({"FATALITIES": "2", "CASUALTIES": "1"}, "casualty_total_mismatch"),
])
def test_sa_invalid_raw_values_block_qa03_with_located_errors(inputs, patch, reason):
    source = derive(inputs, **patch)
    assert reason in source.errors[RAW_ID]
    result = qa.qa03(source, source.by_role["crash"], [])
    assert result["result"] == "block" and reason in result["evidence"]["reason_codes"]
    assert any(r.get("reference", {}).get("raw_record_id") == RAW_ID for r in result["_details"])


@pytest.mark.parametrize("patch,reason", [
    ({"LATITUDE": ""}, "missing"), ({"LONGITUDE": "181"}, "invalid_coordinate"),
    ({"LATITUDE": "NaN"}, "invalid_coordinate"),
])
def test_sa_unusable_coordinates_keep_crash_but_clear_map_fields(inputs, patch, reason):
    source = derive(inputs, **patch)
    row, = source.projected["syn_sa_crash"]
    assert not source.errors and row["map_eligible"] is False
    assert all(row[k] is None for k in ("latitude", "longitude", "location_crs", "location_record_id"))
    assert row["_location_reason"] == reason


def test_sa_qa05_rejects_same_wrong_total_in_projection_and_canonical(inputs):
    source = derive(inputs)
    wrong = {k: v for k, v in source.projected["syn_sa_crash"][0].items() if not k.startswith("_")}
    wrong.update(casualty_count=2, quality_notes={})
    result = qa.qa05(source, [("crash", wrong)], [wrong], [], qa.Findings())
    assert result["result"] == "block"
    assert "semantic_values" in result["evidence"]["reason_codes"]
    assert any("casualty_count" in row["mismatched_fields"] for row in result["_details"])


@pytest.mark.parametrize("year", ["2019", "2025"])
def test_sa_qa07_keeps_outside_year_detection(inputs, year):
    source = derive(inputs, YEAR=year)
    row, = source.all_crashes
    assert not source.projected["syn_sa_crash"] and source.raw_year({"YEAR": year}) == int(year)
    unexpected = {k: v for k, v in row.items() if not k.startswith("_")}
    result = qa.qa07(source, int(year), [unexpected], [unexpected])
    assert result["result"] == "block"
    assert "outside_analysis_year" in result["evidence"]["reason_codes"]
    assert result["expected"]["evaluated_count"] == 0


@pytest.mark.parametrize("year", ["1900", "2100"])
def test_sa_canonical_year_boundaries_are_valid_but_outside_s0_analysis(inputs, year):
    source = derive(inputs, YEAR=year)
    assert not source.errors
    assert source.raw_year({"YEAR": year}) == int(year)
    assert len(source.all_crashes) == 1 and not source.projected["syn_sa_crash"]
    result = qa.qa03(source, source.by_role["crash"], [])
    assert result["result"] == "pass"
    assert result["actual"]["metrics"]["excluded_count"] == 1


def test_sa_qa07_keeps_invalid_month_under_its_native_year(inputs):
    source = derive(inputs, YEAR="2019", MONTH="invalid")
    assert source.raw_year(source.rows("crash")[0]["payload"]) == 2019
    result = qa.qa07(source, 2019, [], [], source.rows("crash"))
    assert result["result"] == "block" and "invalid_raw_crash" in result["evidence"]["reason_codes"]


def test_sa_source_rejects_official_namespace_claim(inputs):
    manifest, source, raw = deepcopy(inputs)
    manifest["dataset_kind"] = "official"
    with pytest.raises(ValueError):
        Source(manifest, source, raw, BATCH)
