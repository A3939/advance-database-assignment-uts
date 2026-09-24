"""C01 typed examples for team v1.1, not a source projection or SQL encoder.

S0 rows are handwritten expectations from 04 section 4. UUIDs are fixture-only
placeholders. Key strings are literal PostgreSQL 16 examples; A05 must produce
and verify real keys in SQL. F cases are separate tests, not one combined batch.
"""

from copy import deepcopy
from datetime import date
from decimal import Decimal
from uuid import UUID


CONTRACT_VERSION = "team-v1.1"
BATCH_ID = UUID("00000000-0000-0000-0000-000000000001")
CRASH_FIELDS = (
    "batch_id", "source_id", "release_scope", "crash_key", "raw_record_id",
    "occurrence_year", "occurrence_month", "occurrence_date", "date_precision",
    "severity_raw", "severity_code", "severity_definition_version",
    "is_fatal_crash", "fatality_count", "casualty_count", "fatal_crash_eligible",
    "fatality_eligible", "casualty_eligible", "latitude", "longitude",
    "location_crs", "map_eligible", "location_record_id", "quality_notes",
)
UNIT_FIELDS = (
    "batch_id", "source_id", "release_scope", "unit_key", "crash_key",
    "raw_record_id", "unit_type_raw", "unit_type_code", "statistical_scope",
    "count_eligible", "quality_notes",
)


def _raw(number):
    return UUID(int=number)


def _field_reason(field, reason="missing", token=None):
    return {
        "field": field, "reason_code": reason, "raw_token": token,
        "contract_version": CONTRACT_VERSION,
    }


def _location(reason, candidates, resolution, evidence):
    return {
        "reason_code": reason,
        "candidate_raw_record_ids": [str(value) for value in candidates],
        "resolution": resolution, "evidence_ref": evidence,
    }


S0_CRASHES = {
    "N1": {
        "batch_id": BATCH_ID, "source_id": "syn_nsw", "release_scope": "s0",
        "crash_key": '["0001"]', "raw_record_id": _raw(1001),
        "occurrence_year": 2020, "occurrence_month": 1,
        "occurrence_date": None, "date_precision": "month",
        "severity_raw": "F", "severity_code": "F",
        "severity_definition_version": "syn-1", "is_fatal_crash": True,
        "fatality_count": 2, "casualty_count": 3,
        "fatal_crash_eligible": True, "fatality_eligible": True,
        "casualty_eligible": True,
        "latitude": Decimal("-33.8600000"), "longitude": Decimal("151.2000000"),
        "location_crs": "EPSG:4326", "map_eligible": True,
        "location_record_id": _raw(1001), "quality_notes": {},
    },
    "N2": {
        "batch_id": BATCH_ID, "source_id": "syn_nsw", "release_scope": "s0",
        "crash_key": '["0002"]', "raw_record_id": _raw(1002),
        "occurrence_year": 2020, "occurrence_month": None,
        "occurrence_date": None, "date_precision": "year",
        "severity_raw": None, "severity_code": "__MISSING__",
        "severity_definition_version": "syn-1", "is_fatal_crash": None,
        "fatality_count": None, "casualty_count": None,
        "fatal_crash_eligible": False, "fatality_eligible": False,
        "casualty_eligible": False, "latitude": None, "longitude": None,
        "location_crs": None, "map_eligible": False, "location_record_id": None,
        "quality_notes": {
            "fields": [_field_reason(field) for field in (
                "severity_raw", "is_fatal_crash", "fatality_count", "casualty_count",
                "fatal_crash_eligible", "fatality_eligible", "casualty_eligible",
            )],
            "location": _location("no_location", [], "retain_crash_without_location", "S0:N2"),
        },
    },
    "V1": {
        "batch_id": BATCH_ID, "source_id": "syn_vic", "release_scope": "s0",
        "crash_key": '["0001"]', "raw_record_id": _raw(3001),
        "occurrence_year": 2020, "occurrence_month": 1,
        "occurrence_date": date(2020, 1, 15), "date_precision": "day",
        "severity_raw": "F", "severity_code": "F",
        "severity_definition_version": "syn-1", "is_fatal_crash": True,
        "fatality_count": 1, "casualty_count": 2,
        "fatal_crash_eligible": True, "fatality_eligible": True,
        "casualty_eligible": True,
        "latitude": Decimal("-37.8000000"), "longitude": Decimal("144.9000000"),
        "location_crs": "EPSG:4326", "map_eligible": True,
        "location_record_id": _raw(6001), "quality_notes": {},
    },
    "V2": {
        "batch_id": BATCH_ID, "source_id": "syn_vic", "release_scope": "s0",
        "crash_key": '["0002"]', "raw_record_id": _raw(3002),
        "occurrence_year": 2021, "occurrence_month": 2,
        "occurrence_date": date(2021, 2, 15), "date_precision": "day",
        "severity_raw": "I", "severity_code": "I",
        "severity_definition_version": "syn-1", "is_fatal_crash": False,
        "fatality_count": 0, "casualty_count": 1,
        "fatal_crash_eligible": True, "fatality_eligible": True,
        "casualty_eligible": True, "latitude": None, "longitude": None,
        "location_crs": None, "map_eligible": False, "location_record_id": None,
        "quality_notes": {"location": _location(
            "location_conflict", [_raw(6003), _raw(6004)],
            "retain_crash_without_location", "S0:V2/NODE02",
        )},
    },
    "Q1": {
        "batch_id": BATCH_ID, "source_id": "syn_qld", "release_scope": "s0",
        "crash_key": '["0001"]', "raw_record_id": _raw(7001),
        "occurrence_year": 2020, "occurrence_month": 1,
        "occurrence_date": None, "date_precision": "month",
        "severity_raw": "I", "severity_code": "I",
        "severity_definition_version": "syn-1", "is_fatal_crash": False,
        "fatality_count": 0, "casualty_count": 1,
        "fatal_crash_eligible": True, "fatality_eligible": True,
        "casualty_eligible": True,
        "latitude": Decimal("-27.4700000"), "longitude": Decimal("153.0200000"),
        "location_crs": "EPSG:4326", "map_eligible": True,
        "location_record_id": _raw(7001), "quality_notes": {},
    },
    "Q2": {
        "batch_id": BATCH_ID, "source_id": "syn_qld", "release_scope": "s0",
        "crash_key": '["0002"]', "raw_record_id": _raw(7002),
        "occurrence_year": 2021, "occurrence_month": 2,
        "occurrence_date": None, "date_precision": "month",
        "severity_raw": "N", "severity_code": "N",
        "severity_definition_version": "syn-1", "is_fatal_crash": False,
        "fatality_count": 0, "casualty_count": 0,
        "fatal_crash_eligible": True, "fatality_eligible": True,
        "casualty_eligible": True,
        "latitude": Decimal("-27.5000000"), "longitude": Decimal("153.0500000"),
        "location_crs": "EPSG:4326", "map_eligible": True,
        "location_record_id": _raw(7002), "quality_notes": {},
    },
}


def _unit(source, unit_key, crash_key, raw_number, scope):
    return {
        "batch_id": BATCH_ID, "source_id": source, "release_scope": "s0",
        "unit_key": unit_key, "crash_key": crash_key,
        "raw_record_id": _raw(raw_number), "unit_type_raw": "CAR",
        "unit_type_code": "CAR", "statistical_scope": scope,
        "count_eligible": True, "quality_notes": {},
    }


S0_UNITS = [
    _unit("syn_nsw", '["0001", "01"]', '["0001"]', 2001, "synthetic_traffic_unit"),
    _unit("syn_nsw", '["0001", "02"]', '["0001"]', 2002, "synthetic_traffic_unit"),
    _unit("syn_nsw", '["0002", "01"]', '["0002"]', 2003, "synthetic_traffic_unit"),
    _unit("syn_vic", '["0001", "01"]', '["0001"]', 4001, "synthetic_vehicle"),
    _unit("syn_vic", '["0002", "01"]', '["0002"]', 4002, "synthetic_vehicle"),
    _unit("syn_vic", '["0002", "02"]', '["0002"]', 4003, "synthetic_vehicle"),
]

# All four observations remain visible. Only V1's first equivalent observation
# supplies location_record_id; this is an expected result, not Node selection code.
S0_NODE_OBSERVATIONS = [
    {"raw_record_id": _raw(6001), "accident_no": "0001", "node_id": "NODE01",
     "row_locator": "csv:1", "latitude": "-37.8", "longitude": "144.9"},
    {"raw_record_id": _raw(6002), "accident_no": "0001", "node_id": "NODE01",
     "row_locator": "csv:2", "latitude": "-37.8", "longitude": "144.9"},
    {"raw_record_id": _raw(6003), "accident_no": "0002", "node_id": "NODE02",
     "row_locator": "csv:3", "latitude": "-37.9", "longitude": "145.0"},
    {"raw_record_id": _raw(6004), "accident_no": "0002", "node_id": "NODE02",
     "row_locator": "csv:4", "latitude": "-38.0", "longitude": "145.1"},
]


def _case(fixture_id, scenario, row, qa):
    return {"fixture_id": fixture_id, "scenario": scenario,
            "expected_shape_valid": True, "expected_qa": qa, "row": deepcopy(row)}


unmapped = deepcopy(S0_CRASHES["V1"])
unmapped.update({
    "severity_raw": "UNMAPPED_NATIVE_VALUE", "severity_code": "UNMAPPED_NATIVE_VALUE",
    "is_fatal_crash": None, "fatal_crash_eligible": False,
    "fatality_eligible": False, "casualty_eligible": False,
    "quality_notes": {"fields": [_field_reason(field, "unmapped", "UNMAPPED_NATIVE_VALUE")
        for field in ("severity_code", "fatal_crash_eligible", "fatality_eligible", "casualty_eligible")]},
})
partial = deepcopy(S0_CRASHES["N1"])
partial.update({"casualty_count": None, "casualty_eligible": False,
                "quality_notes": {"fields": [_field_reason("casualty_count"),
                                               _field_reason("casualty_eligible")]}})

CRASH_FIXTURES = [
    _case("F01", "normal_crash", S0_CRASHES["V1"], {"QA05_SEMANTICS": "pass"}),
    _case("F02", "defined_missing_values", S0_CRASHES["N2"], {"QA05_SEMANTICS": "pass", "QA07_LOCATION": "limited"}),
    _case("F03", "undefined_nonempty_category", unmapped, {"QA05_SEMANTICS": "block"}),
    _case("F04A", "same_native_id_nsw", S0_CRASHES["N1"], {"QA03_PROJECTED": "pass"}),
    _case("F04B", "same_native_id_vic", S0_CRASHES["V1"], {"QA03_PROJECTED": "pass"}),
    _case("F07", "node_lineage", S0_CRASHES["V1"], {"QA07_LOCATION": "pass"}),
    _case("F08", "same_row_lineage", S0_CRASHES["Q1"], {"QA07_LOCATION": "pass"}),
    _case("F09", "conflicting_node_observations", S0_CRASHES["V2"], {"QA07_LOCATION": "limited"}),
    _case("F10", "qld_no_individual_units", S0_CRASHES["Q2"], {"QA03_PROJECTED": "pass"}),
    _case("F11", "independent_count_eligibility", partial, {"QA05_SEMANTICS": "pass"}),
]
CRASH_FIXTURES[8]["expected_unit_rows"] = 0

orphan = deepcopy(S0_UNITS[3])
orphan.update({
    "unit_key": '["0999", "01"]', "crash_key": '["0999"]',
    "raw_record_id": _raw(4099), "count_eligible": False,
    "quality_notes": {"references": [{"relation": "parent_crash",
        "raw_record_id": str(_raw(4099)), "evidence_ref": "F06:parent_0999_absent"}]},
})
UNIT_FIXTURES = [
    _case("F05", "real_unit_with_parent", S0_UNITS[3], {"QA03_PROJECTED": "pass", "QA04_AUXILIARY": "pass"}),
    _case("F06", "absent_parent", orphan, {"QA03_PROJECTED": "block", "QA04_AUXILIARY": "block"}),
]


def validate_fixture_shapes():
    """Check explicit columns only; pytest covers the separate fixture rules."""
    for fields, fixtures in ((CRASH_FIELDS, CRASH_FIXTURES), (UNIT_FIELDS, UNIT_FIXTURES)):
        for fixture in fixtures:
            if set(fixture["row"]) != set(fields):
                raise ValueError(f"{fixture['fixture_id']}: incorrect projection fields")


if __name__ == "__main__":
    validate_fixture_shapes()
    print("C01 fixture shapes match 24/11 fields; this does not run SQL or QA.")
