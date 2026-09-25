"""AT15 native inputs and manifest assembly; no database or business SQL is run."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from arsia_ingest.manifest import REQUIRED_CHECKS, build_manifest, read_json, s0_definitions
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.qa_input import check_inputs
from test_manifest import ROOT, assemble, build
from test_s0 import read_native, s0


S8_HEADERS = ["CRASH_ID", "YEAR", "MONTH", "SEVERITY", "FATALITIES", "CASUALTIES", "LATITUDE", "LONGITUDE"]
S8_ROW = {"CRASH_ID": "0001", "YEAR": "2020", "MONTH": "01", "SEVERITY": "F",
          "FATALITIES": "1", "CASUALTIES": "1", "LATITUDE": "-34.92", "LONGITUDE": "138.60"}
BASELINE = ROOT / "tests/fixtures/s0"


def _bytes(directory):
    return {path.name: path.read_bytes() for path in directory.iterdir() if path.is_file()}


def _native_paths(config_path):
    return {item["resource_id"]: config_path.parent / item["path"]
            for item in read_json(config_path)["resources"]}


def _l1(prepared):
    return {item["resource_id"]: [json.loads(line) for line in
            (Path(prepared["run_dir"]) / item["records_path"]).read_text().splitlines()]
            for item in prepared["files"]}


def _expanded(build, tmp_path, variant):
    config = s0.create_s0(tmp_path / variant, variant)
    prepared = prepare(config, build[0].parents[2])
    assert prepared["status"] == "prepared"
    definitions = s0_definitions(config.parent / "contract.json")
    # Reuse the existing test-only code inventory, never a production build claim.
    kwargs = {**build[1], **definitions, "origins": {
        item["id"]: {"download_url": None, "evidence_ref": f"{variant}/contract.json"}
        for item in definitions["contracts"]}}
    frozen = build_manifest(prepared["run_dir"], **kwargs)
    return config, prepared, kwargs, frozen


@pytest.mark.parametrize("variant,key", [("s8", "0001"), ("s8_bad_key", "   ")])
def test_s8_native_preparation_retains_every_field_and_original_key(tmp_path, variant, key):
    baseline_before = _bytes(BASELINE)
    config_path = s0.create_s0(tmp_path / variant, variant)
    config = read_json(config_path)
    native = read_native(config_path.parent)
    prepared = prepare(config_path, tmp_path / "intake")
    assert (prepared["status"], prepared["raw_count"]) == ("prepared", 20)
    assert len(config["resources"]) == 8
    assert {item["source_id"] for item in config["resources"]} == {"syn_nsw", "syn_vic", "syn_qld", "syn_sa"}
    assert sum(len(item["header"]) for item in config["resources"]) == 205
    assert len([item for item in config["resources"] if item["source_id"] == "syn_sa"]) == 1
    sa = next(item for item in config["resources"] if item["resource_id"] == "syn_sa_crash")
    assert sa["entity_kind"] == "crash" and sa["format"] == "csv"
    assert sa["header"] == S8_HEADERS
    assert native["syn_sa_crash"] == [{**S8_ROW, "CRASH_ID": key}]

    records = _l1(prepared)
    assert len(records) == 8 and sum(map(len, records.values())) == 20
    for rid, rows in records.items():
        assert [row["payload"] for row in rows] == native[rid]
        assert all(set(row) == {"source_id", "resource_id", "file_sha256", "parser_version", "row_locator", "payload"}
                   for row in rows)
    assert records["syn_sa_crash"][0]["row_locator"] == "csv:1"
    assert records["syn_sa_crash"][0]["source_id"] == "syn_sa"
    assert records["syn_sa_crash"][0]["payload"]["LONGITUDE"] == "138.60"
    for rid, baseline_path in _native_paths(BASELINE / "config.json").items():
        assert _native_paths(config_path)[rid].read_bytes() == baseline_path.read_bytes()
    assert _bytes(BASELINE) == baseline_before
    assert "batch_id" not in prepared and "input_fingerprint" not in prepared
    assert read_json(config_path.parent / "contract.json")["variant"]["test_status"] == "NOT_RUN"


def test_bad_key_variant_changes_only_the_s8_key_and_file_hash(tmp_path):
    normal = s0.create_s0(tmp_path / "normal", "s8")
    bad = s0.create_s0(tmp_path / "bad", "s8_bad_key")
    first, second = read_native(normal.parent), read_native(bad.parent)
    assert second["syn_sa_crash"][0]["CRASH_ID"] == "   "
    second["syn_sa_crash"][0]["CRASH_ID"] = "0001"
    assert first == second
    first_files = _native_paths(normal)
    second_files = _native_paths(bad)
    changed = {rid for rid in first_files
               if hashlib.sha256(first_files[rid].read_bytes()).digest()
               != hashlib.sha256(second_files[rid].read_bytes()).digest()}
    assert changed == {"syn_sa_crash"}


@pytest.mark.parametrize("variant", ["s8", "s8_bad_key"])
def test_s8_manifest_adds_one_source_without_changing_the_original_seven(build, tmp_path, variant):
    baseline = assemble(build).as_dict()
    config, prepared, _, frozen = _expanded(build, tmp_path, variant)
    value = frozen.as_dict()
    assert len(value["sources"]) == 4 and len(value["files"]) == 8
    assert sum(item["raw_count"] for item in value["files"]) == 20
    assert value["required_checks"] == list(REQUIRED_CHECKS)
    assert len(value["rules"]["severity"]) == 16
    sa = next(item for item in value["sources"] if item["source_id"] == "syn_sa")
    assert sa["jurisdiction_code"] == "SA"
    assert sa["release_scope"] == "s0" and sa["release_label"] == "Synthetic S8 v1"
    assert sa["resource_ids"] == ["syn_sa_crash"]
    assert [item for item in value["sources"] if item["source_id"] != "syn_sa"] == baseline["sources"]
    assert [item for item in value["files"] if item["source_id"] != "syn_sa"] == baseline["files"]
    for group in ("contracts", "mappings"):
        old_ids = {item["id"] for item in baseline["rules"][group]}
        assert [item for item in value["rules"][group] if item["id"] in old_ids] == baseline["rules"][group]
    assert [item for item in value["rules"]["severity"] if item["source_id"] != "syn_sa"] == baseline["rules"]["severity"]
    assert value["analysis"] == baseline["analysis"]
    assert value["rules"]["qa_contract"] == baseline["rules"]["qa_contract"]

    sa_file = next(item for item in value["files"] if item["resource_id"] == "syn_sa_crash")
    sa_contract = next(item for item in value["rules"]["contracts"] if item["id"] == "syn_sa_crash")
    source_definition = next(item for item in read_json(config.parent / "contract.json")["resources"]
                             if item["resource_id"] == "syn_sa_crash")
    digest = hashlib.sha256(_native_paths(config)["syn_sa_crash"].read_bytes()).hexdigest()
    assert sa_file["file_sha256"] == digest == source_definition["native"]["expected_sha256"]
    assert sa_contract["content"]["input"] == sa_file
    assert sa_contract["content"]["identity"]["key"]["fields"] == ["CRASH_ID"]
    assert sa_contract["content"]["identity"]["parent"] is None
    assert sa_contract["status"] == "synthetic_defined"
    assert sa_contract["version"] == source_definition["fixture_version"] == "s8-native-v1"
    coverage = sa_contract["content"]["identity"]["coverage"]
    assert coverage == source_definition["coverage"]
    assert (coverage["year_from"], coverage["year_to"], coverage["months"]) == (2020, 2024, list(range(1, 13)))
    assert coverage["basis"] != baseline["rules"]["contracts"][0]["content"]["identity"]["coverage"]["basis"]
    assert "AT15" in sa_contract["content"]["confirmation"]["basis"]
    assert source_definition["mapping"]["location"]["crs"] == "EPSG:4326"
    assert source_definition["mapping"]["location"]["latitude"] == "LATITUDE"
    assert source_definition["mapping"]["location"]["longitude"] == "LONGITUDE"
    assert {item["severity_code"]: item["is_fatal_crash"] for item in value["rules"]["severity"]
            if item["source_id"] == "syn_sa"} == {"F": True, "I": False, "N": False, "__MISSING__": None}
    assert value["files"] == sorted(read_json(Path(prepared["run_dir"]) / "files.json")["files"],
                                     key=lambda item: item["resource_id"])
    assert "provenance" not in frozen.fingerprint_input()


@pytest.mark.parametrize("variant", ["s8", "s8_bad_key"])
def test_s8_input_checks_accept_the_extension_with_explicit_test_mapping_support(build, tmp_path, variant):
    baseline = assemble(build).as_dict()
    _, _, _, frozen = _expanded(build, tmp_path, variant)
    value = frozen.as_dict()
    report = check_inputs(value, build[0].parents[2], previous_manifest=baseline,
                          evidence_dir=tmp_path / "qa", producer_version="s8-input-test-v1",
                          supported_mappings=value["rules"]["mappings"])
    assert not report.blocked and len(report.rows) == 9
    assert all(row["actual"] == row["expected"] for row in report.rows[:-1])
    assert report.rows[-1]["actual"]["metrics"] == {
        "object_count": 8, "pass_count": 8, "limited_count": 0, "block_count": 0, "missing_count": 0,
    }
    # QA01 checks the input snapshot; C must reject the whitespace business key.
    assert all(row["rule_id"] == "QA01_INPUT" for row in report.rows)


@pytest.mark.parametrize("accepted", ["none", "baseline_only"])
def test_s8_does_not_imply_an_installed_projection_mapping(build, tmp_path, accepted):
    baseline = assemble(build).as_dict()
    _, _, _, frozen = _expanded(build, tmp_path, "s8")
    kwargs = {} if accepted == "none" else {"supported_mappings": baseline["rules"]["mappings"]}
    report = check_inputs(frozen.as_dict(), build[0].parents[2], previous_manifest=baseline,
                          evidence_dir=tmp_path / "qa", producer_version="s8-input-test-v1", **kwargs)
    assert report.blocked
    blocked = [row for row in report.rows[:-1] if row["result"] == "block"]
    assert len(blocked) == (8 if accepted == "none" else 1)
    sa = next(row for row in blocked if row["object_key"].startswith("file:syn_sa_crash:"))
    assert sa["evidence"]["reason_codes"] == ["MAPPING_UNSUPPORTED"]


def test_s8_manifest_still_requires_the_complete_build_inventory(build, tmp_path):
    _, prepared, kwargs, _ = _expanded(build, tmp_path, "s8")
    kwargs = deepcopy(kwargs)
    del kwargs["inventory"]["components"]["fp1"]
    with pytest.raises(IntakeError) as error:
        build_manifest(prepared["run_dir"], **kwargs)
    assert error.value.code == "MANIFEST_VERSION_MISSING"


@pytest.mark.parametrize("variant,directory_name", [("s8", "s8"), ("s8_bad_key", "s8-bad-key")])
def test_shared_s8_fixtures_reproduce_without_copying_or_changing_s0(tmp_path, variant, directory_name):
    baseline = tmp_path / "s0"
    shutil.copytree(BASELINE, baseline)
    before = _bytes(baseline)
    output = tmp_path / directory_name
    config = s0.create_s0(output, variant, reuse_s0=baseline)
    assert set(_bytes(output)) == {"config.json", "contract.json", "syn_sa_crash.csv"}
    assert _bytes(output) == _bytes(ROOT / "tests/fixtures" / directory_name)
    assert _bytes(baseline) == before
    for rid, path in _native_paths(config).items():
        assert path.resolve().parent == (output if rid == "syn_sa_crash" else baseline)
    prepared = prepare(config, tmp_path / "intake")
    assert (prepared["status"], prepared["raw_count"]) == ("prepared", 20)


@pytest.mark.parametrize("variant", ["s8", "s8_bad_key"])
def test_s8_generator_refuses_to_replace_existing_work(tmp_path, variant):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("Keep this work.\n")
    before = _bytes(output)
    with pytest.raises(ValueError):
        s0.create_s0(output, variant, reuse_s0=BASELINE)
    assert _bytes(output) == before


def test_s8_reuse_rejects_changed_baseline_bytes_without_overwriting_them(tmp_path):
    baseline = tmp_path / "s0"
    shutil.copytree(BASELINE, baseline)
    original = baseline / "syn_vic_accident.csv"
    original.write_bytes(original.read_bytes() + b"\r\n")
    before = _bytes(baseline)
    output = tmp_path / "s8"
    with pytest.raises(ValueError):
        s0.create_s0(output, "s8", reuse_s0=baseline)
    assert _bytes(baseline) == before
    assert not output.exists() or not list(output.iterdir())


def test_s0_does_not_accept_the_s8_reuse_option(tmp_path):
    output = tmp_path / "s0"
    with pytest.raises(ValueError):
        s0.create_s0(output, "s0", reuse_s0=BASELINE)
    assert not output.exists() or not list(output.iterdir())
