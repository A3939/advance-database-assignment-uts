from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> dict[str, object]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_nsw_confirmed_inputs_match_frozen_native_config() -> None:
    package = _read("config/official-nsw-v1.json")
    native = _read("config/native-inputs.json")
    native_by_id = {
        value["resource_id"]: value
        for value in native["resources"]  # type: ignore[index]
        if value["resource_id"].startswith("official_nsw")
    }
    contracts = package["contracts"]  # type: ignore[index]
    assert {value["resource_id"] for value in contracts} == set(native_by_id)

    for contract in contracts:
        resource_id = contract["resource_id"]
        frozen = native_by_id[resource_id]
        review_input = contract["input"]
        assert set(review_input) == {
            "source_id",
            "resource_id",
            "resource_role",
            "entity_kind",
            "file_sha256",
            "parser_version",
            "locator_version",
            "format",
            "encoding",
            "sheet",
            "header_row",
            "header",
            "raw_count",
        }
        for field in (
            "source_id",
            "resource_id",
            "resource_role",
            "entity_kind",
            "format",
            "encoding",
            "sheet",
            "header_row",
            "header",
        ):
            assert review_input[field] == frozen[field]
        assert review_input["file_sha256"] == frozen["expected_sha256"]
        assert review_input["parser_version"] == "xlsx-native-v1"
        assert review_input["locator_version"] == "xlsx-physical-v1"


def test_nsw_observations_match_recorded_scan() -> None:
    package = _read("config/official-nsw-v1.json")
    evidence = _read(
        "docs/sources/evidence/nsw/nsw-source-validation-2026-09-23.json"
    )
    full = package["observed_validation"]["full_snapshot"]  # type: ignore[index]
    analysis = package["observed_validation"]["analysis_2020_2024"]  # type: ignore[index]
    crash = evidence["files"]["official_nsw_crash"]  # type: ignore[index]
    unit = evidence["files"]["official_nsw_traffic_unit"]  # type: ignore[index]
    relationship = evidence["relationship"]  # type: ignore[index]

    assert full["crash_rows"] == crash["raw_count"] == 92_189
    assert full["traffic_unit_rows"] == unit["raw_count"] == 170_962
    assert full["duplicate_crash_keys"] == crash["duplicate_crash_key_rows"] == 0
    assert full["duplicate_traffic_unit_keys"] == unit["duplicate_composite_key_rows"] == 0
    assert full["orphan_traffic_units"] == unit["orphan_unit_rows"] == 0
    assert full["declared_unit_count_mismatches"] == relationship["declared_unit_count_mismatches"] == 0
    assert full["reporting_occurrence_year_differences"] == crash["reporting_occurrence_year_differences"] == 488
    assert analysis == evidence["analysis_scope_2020_2024"]


def test_nsw_rules_retain_required_categories_and_no_map() -> None:
    package = _read("config/official-nsw-v1.json")
    contracts = {
        value["resource_id"]: value
        for value in package["contracts"]  # type: ignore[index]
    }
    crash = contracts["official_nsw_crash"]
    unit = contracts["official_nsw_traffic_unit"]
    location = crash["semantics"]["location"]
    assert location == {
        "latitude": "Latitude",
        "longitude": "Longitude",
        "crs": None,
        "reason_code": "crs_unconfirmed",
        "map_enabled": False,
        "rule": "Retain exact native coordinate text and all crashes, including island records. Do not infer a datum from plausible values or a mainland bounding box.",
    }
    assert unit["identity"]["key"]["fields"] == ["Crash ID", "Traffic unit ID"]
    assert len(unit["semantics"]["unit_type_groups"]) == 11
    assert "Pedestrian" in unit["semantics"]["unit_type_groups"]
    assert "Other or unknown" in unit["semantics"]["unit_type_groups"]

    severity = package["severity"]
    labels = {value["severity_label"] for value in severity["categories"]}
    assert labels == {
        "Fatal",
        "Serious Injury",
        "Moderate Injury",
        "Minor/Other Injury",
        "Uncategorised Injury",
        "Non-casualty (towaway)",
        "Unknown",
    }
    fatal = next(value for value in severity["categories"] if value["severity_code"] == "FATAL")
    missing = next(value for value in severity["categories"] if value["severity_code"] == "__MISSING__")
    assert fatal["is_fatal_crash"] is True
    assert missing["is_fatal_crash"] is None


def test_nsw_owner_investigation_does_not_claim_joint_confirmation() -> None:
    package = _read("config/official-nsw-v1.json")
    handoff = _read(
        "docs/sources/evidence/nsw/nsw-source-confirmation-2026-09-23.json"
    )
    assert package["status"] == handoff["status"] == "draft"
    assert package["confirmed_by"] == handoff["confirmed_by"] == "Role A / JJ"
    assert package["reviewed_by"] is handoff["reviewed_by"] is None
    assert package["confirmation"]["contract_confirmed"] is False
    assert handoff["contract_confirmed"] is False
    assert package["confirmation"]["bundle_confirmed"] is True
    assert handoff["bundle_confirmed"] is True
    assert package["confirmation"]["status"] == "draft"
    assert package["owner_investigation_status"] == handoff["owner_investigation_status"] == "completed"
    pending = package["confirmation"]["unresolved"]
    assert len(pending) == 1 and "Role C review" in pending[0]
    assert {review["resource_id"] for review in handoff["reviews"]} == {
        contract["resource_id"] for contract in package["contracts"]
    }
    assert all(contract["status"] == "draft" for contract in package["contracts"])
    for review in handoff["reviews"]:
        assert review["status"] == "draft"
        assert review["confirmed_by"] == "Role A / JJ"
        assert review["reviewed_by"] is None
        assert review["bundle_confirmed"] is True
        assert review["unresolved"] == pending


def test_nsw_contract_has_project_rule_versions_and_mappings() -> None:
    package = _read("config/official-nsw-v1.json")
    contracts = {value["resource_id"]: value for value in package["contracts"]}
    mappings = {value["id"]: value for value in package["mappings"]}
    assert contracts["official_nsw_crash"]["contract_version"] == "nsw-crash-contract-v1"
    assert contracts["official_nsw_traffic_unit"]["contract_version"] == "nsw-traffic-unit-contract-v1"
    assert contracts["official_nsw_crash"]["mapping_ids"] == ["nsw-crash-projection-v1"]
    assert contracts["official_nsw_traffic_unit"]["mapping_ids"] == ["nsw-traffic-unit-projection-v1"]
    assert set(mappings) == {"nsw-crash-projection-v1", "nsw-traffic-unit-projection-v1"}
    assert package["severity"]["definition_version"] == "nsw-crash-severity-v1"
