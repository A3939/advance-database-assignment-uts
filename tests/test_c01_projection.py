"""Independent C01 fixture checks from team 02/04/05, without a database."""

from copy import deepcopy
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import runpy
from uuid import UUID

import pytest


ROOT = Path(__file__).resolve().parents[1]
F = runpy.run_path(str(ROOT / "tests/fixtures/c01/c01_projection.py"))
# Keep this expectation independent of the fixture's field constants.
CRASH_SCHEMA = {
    "batch_id": (UUID, False), "source_id": (str, False),
    "release_scope": (str, False), "crash_key": (str, False),
    "raw_record_id": (UUID, False), "occurrence_year": (int, False),
    "occurrence_month": (int, True), "occurrence_date": (date, True),
    "date_precision": (str, False), "severity_raw": (str, True),
    "severity_code": (str, False), "severity_definition_version": (str, False),
    "is_fatal_crash": (bool, True), "fatality_count": (int, True),
    "casualty_count": (int, True), "fatal_crash_eligible": (bool, False),
    "fatality_eligible": (bool, False), "casualty_eligible": (bool, False),
    "latitude": (Decimal, True), "longitude": (Decimal, True),
    "location_crs": (str, True), "map_eligible": (bool, False),
    "location_record_id": (UUID, True), "quality_notes": (dict, False),
}
UNIT_SCHEMA = {
    "batch_id": (UUID, False), "source_id": (str, False),
    "release_scope": (str, False), "unit_key": (str, False),
    "crash_key": (str, False), "raw_record_id": (UUID, False),
    "unit_type_raw": (str, True), "unit_type_code": (str, True),
    "statistical_scope": (str, False), "count_eligible": (bool, False),
    "quality_notes": (dict, False),
}
REASONS = {"missing", "unmapped", "definition_unconfirmed", "invalid_coordinate",
           "crs_unconfirmed", "location_conflict", "no_location"}
CRASHES = F["S0_CRASHES"]
UNITS = F["S0_UNITS"]
CASES = {case["fixture_id"]: case
         for case in F["CRASH_FIXTURES"] + F["UNIT_FIXTURES"]}


def identity(row, key="crash_key"):
    return tuple(row[field] for field in ("batch_id", "source_id", "release_scope", key))


def check_fields(row, schema):
    assert set(row) == set(schema)
    for field, (kind, nullable) in schema.items():
        value = row[field]
        if value is None:
            assert nullable, field
        else:
            assert type(value) is kind, field
    notes = row["quality_notes"]
    json.dumps(notes, allow_nan=False)
    assert set(notes) <= {"fields", "location", "references"}
    for item in notes.get("fields", []):
        assert set(item) == {"field", "reason_code", "raw_token", "contract_version"}
        assert item["field"] in schema
        assert item["reason_code"] in REASONS
        assert item["contract_version"] == "team-v1.1"
    if "location" in notes:
        assert set(notes["location"]) == {
            "reason_code", "candidate_raw_record_ids", "resolution", "evidence_ref"}
        assert notes["location"]["reason_code"] in REASONS
        for raw_id in notes["location"]["candidate_raw_record_ids"]:
            UUID(raw_id)


def test_field_constants_and_document_match_independent_schema():
    assert tuple(CRASH_SCHEMA) == F["CRASH_FIELDS"]
    assert tuple(UNIT_SCHEMA) == F["UNIT_FIELDS"]
    doc = (ROOT / "docs/role-c/c01-projection-contract.md").read_text(encoding="utf-8")
    sql_types = {UUID: "uuid", str: "text", int: "integer", date: "date",
                 bool: "boolean", Decimal: "numeric(10, 7)", dict: "jsonb"}
    for heading, schema in (("## 2. I_crash", CRASH_SCHEMA), ("## 3. I_unit", UNIT_SCHEMA)):
        section = doc.split(heading + "\n", 1)[1].split("\n## ", 1)[0]
        actual = {}
        for line in section.splitlines():
            if line.startswith("| `"):
                field, sql_type, nullable = [v.strip(" `") for v in line.split("|")[1:4]]
                actual[field] = (sql_type, nullable)
        assert actual == {field: (sql_types[kind], "Yes" if nullable else "No")
                          for field, (kind, nullable) in schema.items()}


@pytest.mark.parametrize("name,row", list(CRASHES.items()) + [
    (case["fixture_id"], case["row"]) for case in F["CRASH_FIXTURES"]])
def test_crash_fields_types_and_constraints(name, row):
    check_fields(row, CRASH_SCHEMA)
    assert 1900 <= row["occurrence_year"] <= 2100
    precision = row["date_precision"]
    assert precision in {"year", "month", "day"}
    if precision == "year":
        assert row["occurrence_month"] is row["occurrence_date"] is None
    else:
        assert 1 <= row["occurrence_month"] <= 12
        if precision == "month":
            assert row["occurrence_date"] is None
        else:
            assert row["occurrence_date"].year == row["occurrence_year"]
            assert row["occurrence_date"].month == row["occurrence_month"]
    for field in ("fatality_count", "casualty_count"):
        assert row[field] is None or row[field] >= 0
    for flag, value in (("fatal_crash_eligible", "is_fatal_crash"),
                        ("fatality_eligible", "fatality_count"),
                        ("casualty_eligible", "casualty_count")):
        if row[flag]:
            assert row[value] is not None
        else:
            assert any(item["field"] in {flag, value}
                       for item in row["quality_notes"].get("fields", []))
    if row["map_eligible"]:
        assert row["location_crs"] == "EPSG:4326"
        assert type(row["location_record_id"]) is UUID
        for field, limit in (("latitude", 90), ("longitude", 180)):
            assert row[field].is_finite() and -limit <= row[field] <= limit
            assert row[field] == row[field].quantize(Decimal("0.0000001"))
    else:
        assert all(row[field] is None for field in (
            "latitude", "longitude", "location_crs", "location_record_id"))
        assert row["quality_notes"]["location"]["reason_code"] in REASONS


@pytest.mark.parametrize("row", UNITS + [case["row"] for case in F["UNIT_FIXTURES"]])
def test_unit_fields_types_and_scope(row):
    check_fields(row, UNIT_SCHEMA)
    assert row["statistical_scope"].strip()
    if row["count_eligible"]:
        assert row["unit_type_code"] is not None
    else:
        assert row["quality_notes"].get("fields") or row["quality_notes"].get("references")
    expected = {"syn_nsw": "synthetic_traffic_unit", "syn_vic": "synthetic_vehicle"}
    assert row["statistical_scope"] == expected[row["source_id"]]


def test_s0_rows_match_hand_calculation():
    # year, month, precision, severity, fatal flag, killed, casualties, map
    expected = {
        "N1": (2020, 1, "month", "F", True, 2, 3, True),
        "N2": (2020, None, "year", "__MISSING__", None, None, None, False),
        "V1": (2020, 1, "day", "F", True, 1, 2, True),
        "V2": (2021, 2, "day", "I", False, 0, 1, False),
        "Q1": (2020, 1, "month", "I", False, 0, 1, True),
        "Q2": (2021, 2, "month", "N", False, 0, 0, True),
    }
    fields = ("occurrence_year", "occurrence_month", "date_precision", "severity_code",
              "is_fatal_crash", "fatality_count", "casualty_count", "map_eligible")
    assert {name: tuple(row[key] for key in fields) for name, row in CRASHES.items()} == expected
    assert all(row["severity_definition_version"] == "syn-1" for row in CRASHES.values())
    for name, row in CRASHES.items():
        assert all(row[flag] is (name != "N2") for flag in (
            "fatal_crash_eligible", "fatality_eligible", "casualty_eligible"))
    assert {name: (row["latitude"], row["longitude"]) for name, row in CRASHES.items()} == {
        "N1": (Decimal("-33.86"), Decimal("151.2")), "N2": (None, None),
        "V1": (Decimal("-37.8"), Decimal("144.9")), "V2": (None, None),
        "Q1": (Decimal("-27.47"), Decimal("153.02")),
        "Q2": (Decimal("-27.5"), Decimal("153.05")),
    }


def test_s0_identities_units_and_no_qld_expansion():
    parents = {identity(row) for row in CRASHES.values()}
    assert len(parents) == 6
    assert len({identity(row, "unit_key") for row in UNITS}) == 6
    assert all(identity(row) in parents for row in UNITS)
    assert {source: sum(row["source_id"] == source for row in UNITS)
            for source in ("syn_nsw", "syn_vic", "syn_qld")} == {
                "syn_nsw": 3, "syn_vic": 3, "syn_qld": 0}
    assert CASES["F10"]["expected_unit_rows"] == 0
    for row in list(CRASHES.values()) + UNITS:
        assert row["release_scope"] == "s0" and row["source_id"].startswith("syn_")
        assert json.loads(row["crash_key"])[0] in {"0001", "0002"}
    for row in UNITS:
        parts = json.loads(row["unit_key"])
        assert parts[0] == json.loads(row["crash_key"])[0]
        assert parts[1] in {"01", "02"}
        assert row["unit_key"] in {'["0001", "01"]', '["0001", "02"]',
                                   '["0002", "01"]', '["0002", "02"]'}


def test_unknown_category_is_not_defined_missing():
    missing, unknown = CASES["F02"], CASES["F03"]
    defined = {"F", "I", "N", "__MISSING__"}
    assert missing["row"]["severity_code"] in defined
    assert missing["expected_qa"]["QA05_SEMANTICS"] == "pass"
    assert unknown["row"]["severity_code"] not in defined
    assert unknown["row"]["severity_raw"] == "UNMAPPED_NATIVE_VALUE"
    assert unknown["expected_shape_valid"] is True
    assert unknown["expected_qa"]["QA05_SEMANTICS"] == "block"


def test_unknown_casualties_do_not_disable_known_fatalities():
    row = CASES["F11"]["row"]
    assert (row["is_fatal_crash"], row["fatality_count"], row["casualty_count"]) == (True, 2, None)
    assert (row["fatal_crash_eligible"], row["fatality_eligible"], row["casualty_eligible"]) == (True, True, False)
    assert CRASHES["N1"]["casualty_count"] == 3  # Separate case, unchanged S0.


def test_orphan_is_explicit_even_with_count_eligibility_false():
    parent_ids = {identity(row) for row in CRASHES.values()}
    valid, orphan = CASES["F05"], CASES["F06"]
    assert identity(valid["row"]) in parent_ids
    assert identity(orphan["row"]) not in parent_ids
    assert orphan["row"]["count_eligible"] is False
    assert orphan["expected_qa"] == {"QA03_PROJECTED": "block", "QA04_AUXILIARY": "block"}
    assert len(parent_ids) == 6


@pytest.mark.parametrize("field,value", [
    ("source_id", "syn_other"), ("release_scope", "s0_other"),
    ("batch_id", UUID("00000000-0000-0000-0000-000000000002")),
])
def test_parent_identity_cannot_cross_scope(field, value):
    row = deepcopy(CASES["F05"]["row"])
    row[field] = value
    assert identity(row) not in {identity(parent) for parent in CRASHES.values()}


def test_location_lineage_and_all_node_observations_retained():
    nodes = F["S0_NODE_OBSERVATIONS"]
    assert len(nodes) == 4
    v1 = [row for row in nodes if row["accident_no"] == "0001"]
    v2 = [row for row in nodes if row["accident_no"] == "0002"]
    assert len({(Decimal(row["latitude"]), Decimal(row["longitude"])) for row in v1}) == 1
    assert len({(Decimal(row["latitude"]), Decimal(row["longitude"])) for row in v2}) == 2
    assert CRASHES["V1"]["location_record_id"] == v1[0]["raw_record_id"]
    assert CRASHES["V1"]["location_record_id"] != CRASHES["V1"]["raw_record_id"]
    assert CRASHES["V2"]["quality_notes"]["location"]["candidate_raw_record_ids"] == [str(row["raw_record_id"]) for row in v2]
    for name in ("N1", "Q1", "Q2"):
        assert CRASHES[name]["location_record_id"] == CRASHES[name]["raw_record_id"]
    assert CASES["F09"]["expected_qa"]["QA07_LOCATION"] == "limited"


def test_shape_guard_detects_field_replacement():
    row = CASES["F01"]["row"]
    original = row.pop("release_scope")
    row["primary_resource_id"] = "syn_vic_accident"
    try:
        with pytest.raises(ValueError, match="incorrect projection fields"):
            F["validate_fixture_shapes"]()
    finally:
        del row["primary_resource_id"]
        row["release_scope"] = original
    F["validate_fixture_shapes"]()
