from __future__ import annotations

import pytest

from arsia_c.projections.nsw import (
    _contract_by_id,
    _mapping_by_id,
    _validate_relationship_counts,
)


def _manifest() -> dict:
    return {
        "rules": {
            "contracts": [
                {
                    "id": "official_nsw_crash",
                    "mapping_ids": ["nsw-crash-projection-v1"],
                },
                {
                    "id": "official_nsw_traffic_unit",
                    "mapping_ids": ["nsw-traffic-unit-projection-v1"],
                },
            ],
            "mappings": [
                {
                    "id": "nsw-crash-projection-v1",
                    "content": {},
                },
                {
                    "id": "nsw-traffic-unit-projection-v1",
                    "content": {"statistical_scope": "NSW traffic units"},
                },
            ],
        }
    }


def test_contract_by_id_returns_exact_contract():
    manifest = _manifest()

    contract = _contract_by_id(
        manifest,
        "official_nsw_crash",
    )

    assert contract["id"] == "official_nsw_crash"


def test_contract_by_id_rejects_missing_contract():
    manifest = _manifest()

    with pytest.raises(
        ValueError,
        match="expected exactly one contract",
    ):
        _contract_by_id(
            manifest,
            "missing_resource",
        )


def test_contract_by_id_rejects_duplicate_contract():
    manifest = _manifest()

    manifest["rules"]["contracts"].append(
        {
            "id": "official_nsw_crash",
            "mapping_ids": ["duplicate-mapping"],
        }
    )

    with pytest.raises(
        ValueError,
        match="expected exactly one contract",
    ):
        _contract_by_id(
            manifest,
            "official_nsw_crash",
        )


def test_mapping_by_id_returns_exact_mapping():
    manifest = _manifest()

    mapping = _mapping_by_id(
        manifest,
        "nsw-traffic-unit-projection-v1",
    )

    assert mapping["content"]["statistical_scope"] == "NSW traffic units"


def test_mapping_by_id_rejects_missing_mapping():
    manifest = _manifest()

    with pytest.raises(
        ValueError,
        match="expected exactly one mapping",
    ):
        _mapping_by_id(
            manifest,
            "missing-mapping",
        )


def test_relationship_validation_accepts_zero_counts():
    _validate_relationship_counts((0, 0, 0, 0, 0))


@pytest.mark.parametrize(
    "counts",
    [
        (1, 0, 0, 0, 0),
        (0, 1, 0, 0, 0),
        (0, 0, 1, 0, 0),
        (0, 0, 0, 1, 0),
        (0, 0, 0, 0, 1),
    ],
)
def test_relationship_validation_blocks_nonzero_counts(
    counts,
):
    with pytest.raises(
        ValueError,
        match="NSW relationship validation failed",
    ):
        _validate_relationship_counts(counts)


def test_relationship_validation_rejects_no_result():
    with pytest.raises(
        ValueError,
        match="returned no result",
    ):
        _validate_relationship_counts(None)


def component_manifest():
    """Actual B09 S0 definitions, NOT a complete build/inventory or FP1 result."""
    from pathlib import Path
    from copy import deepcopy
    from arsia_ingest.manifest import s0_definitions

    definitions = s0_definitions(
        Path(__file__).resolve().parents[1] / "tests/fixtures/s0/contract.json"
    )
    return {
        "dataset_kind": "synthetic",
        "analysis": definitions["analysis"],
        "sources": definitions["sources"],
        "files": [deepcopy(c["content"]["input"]) for c in definitions["contracts"]],
        "rules": {k: definitions[k] for k in ("contracts", "mappings", "severity")},
    }


def test_real_b09_s0_definitions_select_synthetic_resources_and_codes():
    from arsia_c.projections.nsw import _parameters
    import json

    p = _parameters(component_manifest(), "00000000-0000-0000-0000-000000000001")
    assert p["crash_resource_id"] == "syn_nsw_crash"
    assert p["unit_resource_id"] == "syn_nsw_traffic_unit"
    assert json.loads(p["unit_types"]) == {"CAR": "CAR"}
    assert json.loads(p["severity_map"])["F"] == {"code": "F", "fatal": True}
    assert p["map_enabled"] is True


@pytest.mark.parametrize(
    "lo,hi", [(True, 2024), (2025, 2020), (0, 2024), (2020, 10000)]
)
def test_invalid_analysis_interval_blocks_before_sql(lo, hi):
    from arsia_c.projections.nsw import _parameters

    value = component_manifest()
    value["analysis"] = {"year_from": lo, "year_to": hi}
    with pytest.raises(ValueError, match="calendar-year"):
        _parameters(value, "unused")


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda m: m["rules"]["contracts"][0].update(status="draft"), "drafts"),
        (
            lambda m: m["rules"]["contracts"][1]["content"]["identity"].update(
                release_scope="other"
            ),
            "release",
        ),
        (
            lambda m: m["rules"]["contracts"][1]["content"]["identity"][
                "parent"
            ].update(resource_id="other"),
            "parent",
        ),
        (
            lambda m: m["rules"]["mappings"][1]["content"].update(unit_types={}),
            "unit type",
        ),
        (
            lambda m: m["rules"]["mappings"][1]["content"].update(
                unit_types={"CAR": None}
            ),
            "unit type",
        ),
        (
            lambda m: m["rules"]["mappings"][0]["content"]["location"].update(
                crs="EPSG:3857"
            ),
            "CRS",
        ),
        (
            lambda m: m["rules"]["mappings"][0]["content"].update(
                fatality_count="other"
            ),
            "field mapping",
        ),
    ],
)
def test_inconsistent_contracts_fail_closed(change, match):
    from arsia_c.projections.nsw import _parameters

    value = component_manifest()
    change(value)
    with pytest.raises(ValueError, match=match):
        _parameters(value, "unused")


def test_official_adapter_uses_declared_labels_and_native_unit_groups():
    """Artificial contract to exercise A04's shape; no real review is inferred."""
    import json
    from arsia_c.projections.nsw import _parameters

    value = json.loads(json.dumps(component_manifest()).replace("syn_", "official_"))
    value["dataset_kind"] = "official"
    for contract in value["rules"]["contracts"]:
        contract["status"] = "confirmed"
    crash, unit = value["rules"]["contracts"][:2]
    cm, um = value["rules"]["mappings"][:2]
    cm["id"] = "nsw-crash-projection-v1"
    crash["mapping_ids"] = [cm["id"]]
    unit["content"]["semantics"]["unit_type_groups"] = [
        "Car/car derivative",
        "Pedestrian",
    ]
    del um["content"]["unit_types"]
    um["content"]["statistical_scope"] = "NSW traffic units"
    p = _parameters(value, "unused")
    assert json.loads(p["severity_map"])["Fatal"] == {"code": "F", "fatal": True}
    assert json.loads(p["unit_types"]) == {
        "Car/car derivative": "Car/car derivative",
        "Pedestrian": "Pedestrian",
    }
    assert p["map_enabled"] is False
