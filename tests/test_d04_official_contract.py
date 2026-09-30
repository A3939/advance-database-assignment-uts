"""D04 accepts the unchanged official Node short form without guessing a join."""

from copy import deepcopy
import json

import pytest

from arsia_d04.reconciliation import _manifest_scope
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from test_official_definitions import definitions_manifest


def identity(manifest, resource):
    return next(c["content"]["identity"] for c in manifest["rules"]["contracts"] if c["id"] == resource)


@pytest.mark.parametrize("reverse_files", [False, True])
def test_real_official_manifest_resolves_all_source_years_without_changing_contract(reverse_files):
    frozen = definitions_manifest()
    assert isinstance(frozen, FrozenManifest)
    manifest = frozen.as_dict()
    if reverse_files:
        manifest["files"].reverse()
    before = deepcopy(manifest)
    parent = identity(manifest, "official_vic_node")["parent"]
    assert "parent_fields" not in parent
    scope = _manifest_scope(manifest)
    assert {(s.source_id, s.year) for s in scope} == {
        (source, year) for source in ("official_nsw", "official_vic", "official_qld")
        for year in range(2020, 2025)
    }
    assert len(scope) == 15
    for entry in scope:
        allowed = json.loads(entry.lineage_json)
        if entry.source_id == "official_vic":
            node = next(a for a in allowed if a["entity_kind"] == "node_raw")
            assert node["parent_resource_id"] == "official_vic_accident"
            assert node["parent_fields"] == node["parent_crash_fields"] == ["ACCIDENT_NO"]
            assert node["key_fields"] == ["ACCIDENT_NO", "NODE_ID"]
    assert manifest == before
    assert frozen.as_dict()["rules"]["contracts"] == manifest["rules"]["contracts"]


@pytest.mark.parametrize("change", [
    "missing_target", "other_source", "wrong_entity", "wrong_child_field", "reordered",
    "duplicate_target", "duplicate_contract", "missing_key", "duplicate_key",
    "missing_fields", "null_explicit", "empty_explicit", "wrong_explicit_type", "unequal_explicit",
])
def test_short_form_rejects_unresolved_or_ambiguous_relations(change):
    # Invalid dictionaries probe D04's boundary; they are not frozen official inputs.
    manifest = definitions_manifest().as_dict()
    node = identity(manifest, "official_vic_node")
    crash = identity(manifest, "official_vic_accident")
    parent = node["parent"]
    if change == "missing_target":
        parent["resource_id"] = "unselected"
    elif change == "other_source":
        parent["resource_id"] = "official_nsw_crash"
    elif change == "wrong_entity":
        parent["resource_id"] = "official_vic_vehicle"
    elif change == "wrong_child_field":
        parent["fields"] = ["NODE_ID"]
    elif change == "reordered":
        crash["key"]["fields"] = ["ACCIDENT_NO", "NODE_ID"]
        parent["fields"] = ["NODE_ID", "ACCIDENT_NO"]
    elif change == "duplicate_target":
        manifest["files"].append(deepcopy(next(f for f in manifest["files"] if f["resource_id"] == "official_vic_accident")))
    elif change == "duplicate_contract":
        manifest["rules"]["contracts"].append(deepcopy(next(c for c in manifest["rules"]["contracts"] if c["id"] == "official_vic_accident")))
    elif change == "missing_key":
        crash["key"].pop("fields")
    elif change == "duplicate_key":
        crash["key"]["fields"] = parent["fields"] = ["ACCIDENT_NO", "ACCIDENT_NO"]
    elif change == "missing_fields":
        parent.pop("fields")
    else:
        parent["parent_fields"] = {
            "null_explicit": None, "empty_explicit": [], "wrong_explicit_type": "ACCIDENT_NO",
            "unequal_explicit": ["ACCIDENT_NO", "NODE_ID"],
        }[change]
    with pytest.raises(IntakeError) as error:
        _manifest_scope(manifest)
    assert error.value.code == "D04_MANIFEST"
