"""S8 contract admission; database behavior is tested separately."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from arsia_c.projections.sa import parameters, project
from arsia_ingest.manifest import s0_definitions

ROOT = Path(__file__).resolve().parents[1]


def manifest_input():
    definitions = s0_definitions(ROOT / "tests/fixtures/s8/contract.json")
    return {"dataset_kind": "synthetic", "sources": definitions["sources"],
            "analysis": definitions["analysis"],
            "files": [deepcopy(c["content"]["input"]) for c in definitions["contracts"]],
            "rules": {k: definitions[k] for k in ("contracts", "mappings", "severity")}}


def test_generated_s8_definition_keeps_direct_counts_and_no_unit_resources():
    p = parameters(manifest_input(), "batch")
    assert p["source_id"] == "syn_sa" and p["severity_version"] == "syn-1"
    assert p["year_from"] == 2020 and p["year_to"] == 2024
    assert list(p["selected"]) == ["crash"]
    assert p["selected"]["crash"]["raw_count"] == 1 and p["map_enabled"]
    assert json.loads(p["severity_map"]) == {
        "F": {"code": "F", "fatal": True}, "I": {"code": "I", "fatal": False},
        "N": {"code": "N", "fatal": False}}


@pytest.mark.parametrize("mutation", ["official", "source", "release", "resources", "duplicate_source",
    "contract_version", "contract_status", "contract_input", "key", "parent", "mapping_version",
    "mapping_field", "mapping_extra", "semantic_dates", "semantic_missing", "severity_bool",
    "severity_missing", "severity_version", "severity_label", "crs", "basis", "analysis", "raw_count"])
def test_changed_s8_contract_is_rejected_before_sql(mutation):
    m = manifest_input()
    source = next(s for s in m["sources"] if s["source_id"] == "syn_sa")
    contract = next(c for c in m["rules"]["contracts"] if c["id"] == "syn_sa_crash")
    mapping = next(v for v in m["rules"]["mappings"] if v["id"] == "syn_sa_crash_mapping")
    severity = next(s for s in m["rules"]["severity"] if s["source_id"] == "syn_sa")
    selected = next(f for f in m["files"] if f["resource_id"] == "syn_sa_crash")
    if mutation == "official": m["dataset_kind"] = "official"
    elif mutation == "source": source["source_id"] = "official_sa"
    elif mutation == "release": source["release_scope"] = "other"
    elif mutation == "resources": source["resource_ids"].append("syn_sa_unit")
    elif mutation == "duplicate_source": m["sources"].append(deepcopy(source))
    elif mutation == "contract_version": contract["version"] = "s8-native-v2"
    elif mutation == "contract_status": contract["status"] = "draft"
    elif mutation == "contract_input": selected["file_sha256"] = "f" * 64
    elif mutation == "key": contract["content"]["identity"]["key"]["unique"] = False
    elif mutation == "parent": contract["content"]["identity"]["parent"] = {"resource_id": "other"}
    elif mutation == "mapping_version": mapping["version"] = "syn-2"
    elif mutation == "mapping_field": mapping["content"]["casualty_count"] = "FATALITIES"
    elif mutation == "mapping_extra": mapping["content"]["casualty_components"] = ["FATALITIES", "CASUALTIES"]
    elif mutation == "semantic_dates": contract["content"]["semantics"]["common_rules"]["dates"] = "Add a day"
    elif mutation == "semantic_missing": contract["content"]["semantics"]["common_rules"]["blank_values"]["csv"] = "NA"
    elif mutation == "severity_bool": severity["is_fatal_crash"] = 1
    elif mutation == "severity_missing": m["rules"]["severity"].remove(severity)
    elif mutation == "severity_version": severity["definition_version"] = "syn-2"
    elif mutation == "severity_label": severity["severity_label"] = "Different meaning"
    elif mutation == "crs": mapping["content"]["location"]["crs"] = "EPSG:3857"
    elif mutation == "basis": mapping["content"]["location"]["basis"] = " "
    elif mutation == "analysis": m["analysis"]["year_from"] = True
    elif mutation == "raw_count": selected["raw_count"] = True
    with pytest.raises(ValueError):
        parameters(m, "batch")


def test_unconfirmed_synthetic_crs_disables_map():
    m = manifest_input()
    next(v for v in m["rules"]["mappings"] if v["id"] == "syn_sa_crash_mapping")["content"]["location"]["crs"] = None
    assert parameters(m, "batch")["map_enabled"] is False


def test_autocommit_is_rejected_without_reading_context_or_sql():
    class Connection:
        autocommit = True

        def cursor(self):
            raise AssertionError("No SQL is allowed before transaction admission")

    with pytest.raises(ValueError, match="caller-owned transaction"):
        project(Connection(), None)
