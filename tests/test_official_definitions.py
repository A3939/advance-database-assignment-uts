"""Official contract transport checks. Full native/SQL runs are separate."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from arsia_c.projections.nsw import _parameters as nsw_parameters
from arsia_c.projections.source_contracts import parameters, qld_definitions
from arsia_ingest.manifest import FrozenManifest, REQUIRED_CHECKS, digest_inventory
from arsia_ingest.models import IntakeError
from arsia_ingest.official_definitions import (
    ADMISSION_PATH, EVIDENCE_PATHS, NSW_PATH, NSW_SHA256,
    official_definitions, official_origins, official_source_reviews,
)
from arsia_ingest.vic_restricted import vic_restricted_definitions


ROOT = Path(__file__).resolve().parents[1]


def definitions_manifest():
    """Real frozen transport object; this does not execute or publish a build."""
    definitions = official_definitions(ROOT)
    inventory = json.loads((ROOT / "config/build-inventory.json").read_text())
    paths = {"components": inventory["components"],
             "schema_files": [entry["path"] for entry in inventory["schema_files"]]}
    inputs = [c["content"]["input"] for c in definitions["contracts"]]
    origins = official_origins(ROOT)
    value = {
        "contract_version": "team-v1.1", "dataset_kind": "official",
        "sources": definitions["sources"], "analysis": definitions["analysis"],
        "files": inputs,
        "rules": {**{k: definitions[k] for k in ("contracts", "mappings", "severity", "qa_contract")},
                  **digest_inventory(ROOT, paths)},
        "required_checks": list(REQUIRED_CHECKS),
        "provenance": {
            "prepared_at": "2026-09-27T00:00:00Z", "prepared_by": "contract transport test only",
            "files": [{"resource_id": f["resource_id"], "file_sha256": f["file_sha256"],
                       "archive_relpath": f"official/archive/sha256/{f['file_sha256'][:2]}/{f['file_sha256']}",
                       "original_filename": f["resource_id"] + "." + f["format"],
                       **origins[f["resource_id"]]} for f in inputs],
        },
    }
    return FrozenManifest(json.dumps(value))


def test_real_frozen_manifest_accepts_all_three_actual_projection_interfaces():
    frozen = definitions_manifest()
    value = frozen.as_dict()
    assert isinstance(frozen, FrozenManifest)
    assert len(value["sources"]) == 3
    assert len(value["files"]) == 7
    assert sum(f["raw_count"] for f in value["files"]) == 2118028
    assert value["required_checks"] == list(REQUIRED_CHECKS)
    assert nsw_parameters(value, "transport-test")["map_enabled"] is False
    assert parameters(value, "transport-test", "QLD")["map_enabled"] is False
    assert parameters(value, "transport-test", "VIC")["map_enabled"] is False


def test_all_native_severity_definitions_survive_even_when_not_observed():
    definitions = official_definitions(ROOT)
    by_source = {s["source_id"]: {d["severity_code"]: d for d in definitions["severity"]
                                 if d["source_id"] == s["source_id"]} for s in definitions["sources"]}
    assert {sid: len(rows) for sid, rows in by_source.items()} == {
        "official_nsw": 7, "official_vic": 5, "official_qld": 6,
    }
    assert "UNCATEGORISED_INJURY" in by_source["official_nsw"]
    assert "PROPERTY_DAMAGE_ONLY" in by_source["official_qld"]
    assert all(rows["__MISSING__"]["is_fatal_crash"] is None for rows in by_source.values())


def test_adaptation_preserves_a04_authorship_and_does_not_invent_c_review():
    original = json.loads((ROOT / NSW_PATH).read_text())
    assert hashlib.sha256((ROOT / NSW_PATH).read_bytes()).hexdigest() == NSW_SHA256
    assert original["owner"] == "Role A / JJ"
    assert original["confirmation"]["reviewed_by"] is None
    definitions = official_definitions(ROOT)
    for item in original["mappings"]:
        adapted = next(m for m in definitions["mappings"] if m["id"] == item["id"].replace("-", "_"))
        assert adapted["content"]["source_mapping_id"] == item["id"]
        assert all(adapted["content"][k] == v for k, v in item["content"].items()
                   if k != "declared_unit_count")
        if "declared_unit_count" in item["content"]:
            assert adapted["content"]["source_declared_unit_count"] == item["content"]["declared_unit_count"]
    for contract in definitions["contracts"]:
        if contract["id"].startswith("official_nsw"):
            confirmation = contract["content"]["confirmation"]
            assert confirmation["source_reviewed_by"] is None
            assert confirmation["confirmed_by"] == "Role A / JJ"
            assert "Role B / Peixian" in confirmation["reviewed_by"]
            assert confirmation["publisher_questions"] == original["confirmation"]["publisher_questions"]
            assert confirmation["limitations"] == original["confirmation"]["limitations"]


def test_vic_and_qld_definitions_are_not_rewritten_or_given_new_approvals():
    combined = official_definitions(ROOT)
    for sid, original in [("official_vic", vic_restricted_definitions()), ("official_qld", qld_definitions())]:
        for key in ("sources", "severity"):
            assert [v for v in combined[key] if v["source_id"] == sid] == original[key]
        contracts = [c for c in combined["contracts"] if c["content"]["input"]["source_id"] == sid]
        assert contracts == original["contracts"]
        ids = {mid for c in contracts for mid in c["mapping_ids"]}
        assert [m for m in combined["mappings"] if m["id"] in ids] == original["mappings"]
    assert all(r["resource_id"].startswith(("official_nsw", "official_qld"))
               for r in official_source_reviews(ROOT))
    assert len(official_source_reviews(ROOT)) == 3


def test_review_records_bind_contract_versions_hashes_and_release_scopes():
    contracts = {c["id"]: c for c in official_definitions(ROOT)["contracts"]}
    for review in official_source_reviews(ROOT):
        contract = contracts[review["resource_id"]]
        assert review["contract_version"] == contract["version"]
        assert review["file_sha256"] == contract["content"]["input"]["file_sha256"]
        assert review["release_scope"] == contract["content"]["identity"]["release_scope"]
        assert review["bundle_confirmed"] is True
        assert review["unresolved"] == []
        assert review["references"]


@pytest.fixture
def copied_admission(tmp_path):
    for relative in [ADMISSION_PATH, *EVIDENCE_PATHS]:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, path)
    return tmp_path


@pytest.mark.parametrize("change", ["missing", "changed", "symlink"])
def test_changed_or_missing_source_evidence_blocks(copied_admission, change):
    path = copied_admission / "docs/sources/evidence/official-decisions-2026-09-23/nsw-review.json"
    path.unlink()
    if change == "changed":
        path.write_text("{}\n")
    elif change == "symlink":
        path.symlink_to(ROOT / path.relative_to(copied_admission))
    with pytest.raises(IntakeError):
        official_definitions(copied_admission)


@pytest.mark.parametrize("change", ["remove", "duplicate", "alter_and_rehash"])
def test_source_definition_cannot_be_replaced_under_the_old_version(copied_admission, change):
    path = copied_admission / ADMISSION_PATH
    admission = json.loads(path.read_text())
    if change == "remove":
        admission["pinned_files"].pop()
    elif change == "duplicate":
        admission["pinned_files"].append(deepcopy(admission["pinned_files"][0]))
    else:
        original = copied_admission / NSW_PATH
        value = json.loads(original.read_text())
        value["contracts"][0]["input"]["raw_count"] -= 1
        original.write_text(json.dumps(value))
        next(p for p in admission["pinned_files"] if p["path"] == NSW_PATH)["sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
    path.write_text(json.dumps(admission))
    with pytest.raises(IntakeError):
        official_definitions(copied_admission)


def test_absolute_project_root_works_outside_source_and_results_are_independent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    initial = official_definitions(ROOT)
    initial["contracts"].clear()
    assert len(official_definitions(ROOT)["contracts"]) == 7
    origins = official_origins(ROOT)
    assert len(origins) == 7
    assert all(o["download_url"].startswith("https://") and (ROOT / o["evidence_ref"]).is_file()
               for o in origins.values())
