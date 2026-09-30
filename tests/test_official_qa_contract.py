"""Official QA interface checks; database and full-volume runs are separate."""

from copy import deepcopy
import json

import pytest

from arsia_c import qa
from arsia_c.qa_expectations import Source
from arsia_c.projections.nsw import _parameters
from arsia_ingest.manifest import s0_definitions
from arsia_ingest.models import IntakeError
from arsia_ingest.official_definitions import ADMISSION_PATH, NSW_PATH, _nsw_definitions
from arsia_ingest.publication import _required_objects
from arsia_ingest.publication_checks import Requirements
from test_official_definitions import ROOT, definitions_manifest


COUNT_FIELD = "No. of traffic units involved"
BATCH = "00000000-0000-0000-0000-000000000001"


def test_count_declaration_keeps_the_a04_field_and_explicit_child_resource():
    manifest = definitions_manifest().as_dict()
    original = json.loads((ROOT / NSW_PATH).read_text())
    contract = next(c for c in original["contracts"] if c["resource_id"] == "official_nsw_crash")
    rule = contract["semantics"]["declared_unit_count"]
    mapping = next(m for m in manifest["rules"]["mappings"] if m["id"] == "nsw_crash_projection_v1")
    assert mapping["content"]["declared_unit_count"] == {k: rule[k] for k in ("field", "resource_id")}
    assert mapping["content"]["source_declared_unit_count"] == COUNT_FIELD
    assert _parameters(manifest, BATCH)["map_enabled"] is False
    n, metrics = Requirements(None, BATCH, manifest).expected("QA04_AUXILIARY", "resource:official_nsw_traffic_unit")
    assert n == next(f["raw_count"] for f in manifest["files"] if f["resource_id"] == rule["resource_id"])
    assert metrics["declared_count_delta"] == 0


@pytest.mark.parametrize("declared,delta,reason", [
    ("1", 0, None), ("2", 1, "declared_unit_count"),
    ("bad", 0, "invalid_declared_unit_count"),
])
def test_c10_uses_the_official_count_rule_and_still_blocks_partial_input(declared, delta, reason):
    manifest = definitions_manifest().as_dict()
    source = next(s for s in manifest["sources"] if s["source_id"] == "official_nsw")
    files = {f["entity_kind"]: f for f in manifest["files"] if f["source_id"] == source["source_id"]}
    # Two unit-test rows exercise the real rule. They cannot satisfy frozen coverage.
    crash = dict.fromkeys(files["crash"]["header"])
    crash.update({"Crash ID": "test-parent", "Year of crash": "2020", "Month of crash": "January",
                  "Degree of crash - detailed": "Fatal", "No. killed": "1", "No. seriously injured": "0",
                  "No. moderately injured": "0", "No. minor-other injured": "0", COUNT_FIELD: declared})
    unit = dict.fromkeys(files["unit"]["header"])
    unit.update({"Crash ID": "test-parent", "Traffic unit ID": "1"})
    raw = {files[kind]["resource_id"]: [{"raw_record_id": f"test-{kind}", "row_locator": "csv:1",
                                        "resource_id": files[kind]["resource_id"], "payload": payload}]
           for kind, payload in [("crash", crash), ("unit", unit)]}
    derived = Source(manifest, source, raw, BATCH)
    result = qa.qa04(derived, files["unit"], None, qa.Findings())
    assert result["result"] == "block"
    assert "incomplete_raw" in result["evidence"]["reason_codes"]
    assert result["actual"]["metrics"]["declared_count_delta"] == delta
    assert result["expected"]["metrics"]["declared_count_delta"] == 0
    if reason:
        assert reason in result["evidence"]["reason_codes"]


@pytest.mark.parametrize("change", ["field", "target", "parent", "shape"])
def test_adapter_rejects_unlinked_or_malformed_declared_count(tmp_path, change):
    original = json.loads((ROOT / NSW_PATH).read_text())
    crash = next(c for c in original["contracts"] if c["resource_id"] == "official_nsw_crash")
    child = next(c for c in original["contracts"] if c["resource_id"] == "official_nsw_traffic_unit")
    if change == "field":
        crash["semantics"]["declared_unit_count"]["field"] = "No. killed"
    elif change == "target":
        crash["semantics"]["declared_unit_count"]["resource_id"] = "unknown"
    elif change == "parent":
        child["identity"]["parent"]["resource_id"] = "unknown"
    else:
        crash["semantics"]["declared_unit_count"] = COUNT_FIELD
    path = tmp_path / NSW_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(original))
    # Call the adapter alone; admission separately rejects changed source bytes.
    with pytest.raises(IntakeError, match="explicit Crash/Traffic Unit relation"):
        _nsw_definitions(tmp_path, json.loads((ROOT / ADMISSION_PATH).read_text()))


def test_s0_dictionary_and_absent_declaration_keep_their_existing_meaning():
    definitions = s0_definitions(ROOT / "tests/fixtures/s0/contract.json")
    manifest = {"dataset_kind": "synthetic", "sources": definitions["sources"],
                "analysis": definitions["analysis"],
                "files": [c["content"]["input"] for c in definitions["contracts"]],
                "rules": {k: definitions[k] for k in ("contracts", "mappings", "severity")}}
    manifest["rules"]["qa_contract"] = json.loads((ROOT / "config/qa-team-v1.1.json").read_text())
    nsw = next(f for f in manifest["files"] if f["entity_kind"] == "unit" and "nsw" in f["source_id"])
    key = "resource:" + nsw["resource_id"]
    assert Requirements(None, BATCH, manifest).expected("QA04_AUXILIARY", key)[1]["declared_count_delta"] == 0
    absent = deepcopy(manifest)
    for mapping in absent["rules"]["mappings"]:
        mapping["content"].pop("declared_unit_count", None)
    assert Requirements(None, BATCH, absent).expected("QA04_AUXILIARY", key)[1]["declared_count_delta"] is None


def test_all_seven_official_requirement_interfaces(monkeypatch):
    manifest = definitions_manifest().as_dict()
    checks = Requirements(None, BATCH, manifest)
    calls = []

    def query(sql, params):
        # Fixed aggregates isolate manifest shape; no database acceptance is claimed.
        calls.append((sql, params))
        return [(2, 0)] if "FILTER" in sql else [(2,)]

    monkeypatch.setattr(checks, "query", query)
    required = _required_objects(manifest)
    assert {k: len(v) for k, v in required.items()} == {
        "QA01_INPUT": 7, "QA02_RAW": 7, "QA03_PROJECTED": 5, "QA04_AUXILIARY": 4,
        "QA05_SEMANTICS": 3, "QA06_RECONCILIATION": 15, "QA07_LOCATION": 15,
    }
    for rule, objects in required.items():
        for key in objects:
            n, metrics = checks.expected(rule, key)
            assert type(n) is int and n >= 0
            assert metrics
            if rule == "QA03_PROJECTED":
                assert metrics["input_count"] == metrics["excluded_count"] + metrics["projected_count"]
            if rule == "QA07_LOCATION":
                assert metrics == {"crash_count": 2, "map_count": 0, "unmapped_count": 2, "invalid_eligible_count": 0}
    assert len(calls) == 50
