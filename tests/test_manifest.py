"""Small native inputs and temporary code inventories; no platform SQL is run."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

from arsia_ingest.fingerprint import FP1Operation, fingerprint
from arsia_ingest.manifest import (
    COMPONENTS, REQUIRED_CHECKS, FrozenManifest, build_manifest, digest_inventory,
    freeze_manifest, read_json, s0_definitions, team_qa_contract, validate_manifest,
)
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from test_fingerprint import DIGEST, ENVIRONMENT, ScriptedConnection


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def build(tmp_path):
    prepared = prepare(ROOT / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert prepared["status"] == "prepared"
    project = tmp_path / "test-project"
    project.mkdir()
    components = {}
    for name in COMPONENTS:
        relative = f"sql/{name}.sql"
        path = project / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"-- {name}: test inventory bytes only, not executable platform code.\n")
        components[name] = [relative]
    (project / "sql/001_schema.sql").write_text("-- Test schema inventory, no migrated database.\n")
    definitions = s0_definitions(ROOT / "tests/fixtures/s0/contract.json")
    kwargs = {
        **definitions, "project_root": project,
        "inventory": {"components": components, "schema_files": ["sql/001_schema.sql"]},
        "qa_contract": read_json(ROOT / "config/qa-team-v1.1.json"),
        "prepared_by": "unit-test", "origins": {
            resource["id"]: {"download_url": None, "evidence_ref": "tests/fixtures/s0/contract.json"}
            for resource in definitions["contracts"]
        },
    }
    return Path(prepared["run_dir"]), kwargs


def assemble(build):
    run, kwargs = build
    return build_manifest(run, **kwargs)


def test_generated_snapshot_variants_preserve_files_counts_and_change_statements(build, tmp_path):
    spec = importlib.util.spec_from_file_location("s0_generator", ROOT / "tools/create_s0_inputs.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    baseline = assemble(build)
    before = baseline.as_dict()
    baseline_files = {f["resource_id"]: f for f in before["files"]}
    variants = {}
    cases = (
        ("revised_n1", "syn_nsw_crash", 2, "correction", ["0001"]),
        ("delete_q2", "syn_qld_crash", 1, "deletion", ["0002"]),
        ("delete_q2_unexplained", "syn_qld_crash", 1, None, None),
    )
    for name, changed_resource, count, change_kind, native_key in cases:
        directory = tmp_path / name
        config_path = generator.create_s0(directory, name)
        source_contract = read_json(directory / "contract.json")
        prepared = prepare(config_path, tmp_path / "variant-intake")
        assert prepared["status"] == "prepared"
        kwargs = {**build[1], **s0_definitions(directory / "contract.json")}
        kwargs["origins"] = {
            rid: {"download_url": None, "evidence_ref": f"{name}/contract.json"}
            for rid in baseline_files
        }
        frozen = build_manifest(prepared["run_dir"], **kwargs)
        value = frozen.as_dict()
        variants[name] = frozen
        files = {f["resource_id"]: f for f in value["files"]}
        contracts = {c["id"]: c["content"] for c in value["rules"]["contracts"]}
        original_resources = {r["resource_id"]: r for r in source_contract["resources"]}
        expected_counts = {rid: f["raw_count"] for rid, f in baseline_files.items()}
        expected_counts[changed_resource] = count
        assert {rid: f["raw_count"] for rid, f in files.items()} == expected_counts
        assert sum(expected_counts.values()) == prepared["raw_count"] == (19 if name == "revised_n1" else 18)
        assert value["files"] == sorted(read_json(Path(prepared["run_dir"]) / "files.json")["files"], key=lambda f: f["resource_id"])

        for resource in read_json(config_path)["resources"]:
            rid = resource["resource_id"]
            digest = hashlib.sha256((directory / resource["path"]).read_bytes()).hexdigest()
            assert digest == resource["expected_sha256"] == original_resources[rid]["native"]["expected_sha256"]
            assert files[rid]["file_sha256"] == digest
            assert contracts[rid]["input"] == files[rid]
        assert {rid for rid in files if files[rid]["file_sha256"] != baseline_files[rid]["file_sha256"]} == {changed_resource}

        change = source_contract.get("snapshot_change")
        if change_kind is None:
            assert "snapshot_change" not in source_contract
        else:
            assert change["kind"] == change_kind and change["native_key"] == native_key
            assert change["source_id"] == files[changed_resource]["source_id"]
            assert change["previous_release_label"] == "Synthetic S0 v1"
            assert change["description"]
        for contract in contracts.values():
            assert contract["snapshot"] == {"policy": source_contract["common_rules"]["snapshot_policy"], "change": change}
        sources = {s["source_id"]: s for s in value["sources"]}
        sid = files[changed_resource]["source_id"]
        assert sources[sid]["release_label"] == ("Synthetic S0 NSW revision 1" if name == "revised_n1" else "Synthetic S0 QLD revision 1")
        assert value["analysis"] == before["analysis"]
        assert value["required_checks"] == before["required_checks"]

    assert variants["delete_q2"].as_dict()["files"] == variants["delete_q2_unexplained"].as_dict()["files"]
    explained = variants["delete_q2"].fingerprint_input()
    unexplained = variants["delete_q2_unexplained"].fingerprint_input()
    assert explained != unexplained
    # B09 retains the missing statement; QA01 decides whether the reduction is allowed.
    for contract in explained["rules"]["contracts"]:
        contract["content"]["snapshot"]["change"] = None
    assert explained == unexplained
    assert baseline.as_dict() == before


def test_assembled_manifest_reaches_fp1_without_provenance(build):
    """Real manifest assembly, scripted SQL replies; no PostgreSQL is executed."""
    frozen = assemble(build)
    assert isinstance(frozen, FrozenManifest)
    before = frozen.as_dict()
    expected = deepcopy(before)
    del expected["provenance"]
    operation = FP1Operation("review_test", "fp1", "test-v1", 160004, "sql/fp1.sql")
    changed = deepcopy(build[1])
    changed["prepared_by"] = "another preparer"
    for origin in changed["origins"].values():
        origin["evidence_ref"] = "another provenance location"
    relocated_evidence = build_manifest(build[0], **changed)
    assert relocated_evidence.as_dict()["provenance"] != before["provenance"]
    for manifest, reply in ((frozen, DIGEST), (relocated_evidence, "fedcba9876543210" * 4)):
        connection = ScriptedConnection([ENVIRONMENT, [(True,)], [(reply,)]])
        assert fingerprint(connection, manifest, operation, project_root=build[1]["project_root"]) == reply
        assert len(connection.calls) == 3
        assert connection.calls[1][1] == ("review_test", "fp1")
        statement, parameters = connection.calls[2]
        assert statement == 'SELECT "review_test"."fp1"(%s::jsonb)'
        assert isinstance(parameters, tuple) and len(parameters) == 1
        sent = json.loads(parameters[0])
        assert sent == expected and "provenance" not in sent
        assert connection.cursor_closed and not connection.replies
    assert frozen.as_dict() == before


@pytest.mark.parametrize("reply", [[], [(None,)]])
def test_assembled_manifest_does_not_accept_a_missing_fp1_result(build, reply):
    frozen = assemble(build)
    before = frozen.as_dict()
    operation = FP1Operation("review_test", "fp1", "test-v1", 160004, "sql/fp1.sql")
    connection = ScriptedConnection([ENVIRONMENT, [(True,)], reply])
    with pytest.raises(IntakeError) as error:
        fingerprint(connection, frozen, operation, project_root=build[1]["project_root"])
    assert error.value.code == "FP1_RESULT"
    assert connection.cursor_closed and not connection.replies
    assert frozen.as_dict() == before


def test_reuses_all_s0_metadata_mappings_and_severity(build):
    frozen = assemble(build)
    manifest = frozen.as_dict()
    assert len(manifest["files"]) == 7
    assert sum(file["raw_count"] for file in manifest["files"]) == 19
    assert manifest["required_checks"] == list(REQUIRED_CHECKS)
    assert len(manifest["rules"]["severity"]) == 12
    original = read_json(ROOT / "tests/fixtures/s0/contract.json")
    mappings = {m["id"]: m["content"] for m in manifest["rules"]["mappings"]}
    for resource in original["resources"]:
        assert mappings[resource["resource_id"] + "_mapping"] == resource["mapping"]
    assert all(item["definition_text"] == original["severity"]["rule"] for item in manifest["rules"]["severity"])
    assert manifest["provenance"]["prepared_at"] == read_json(build[0] / "run.json")["finished_at"]
    assert "input_path" not in json.dumps(manifest)


def test_freeze_copies_inputs_and_reads_return_disposable_copies(build):
    frozen = assemble(build)
    original = frozen.as_dict()
    build[1]["sources"][0]["source_name"] = "changed after freeze"
    modified = frozen.as_dict()
    modified["files"].clear()
    assert frozen.as_dict() == original
    with pytest.raises(FrozenInstanceError):
        frozen._json = "{}"


def test_provenance_and_relocation_do_not_change_sql_input(build, tmp_path):
    first = assemble(build)
    relocated = tmp_path / "relocated"
    shutil.copytree(build[0].parents[2], relocated)
    run = relocated / "synthetic/runs" / build[0].name
    kwargs = deepcopy(build[1])
    kwargs["prepared_by"] = "another preparer"
    for origin in kwargs["origins"].values():
        origin["evidence_ref"] = "another evidence location"
    second = build_manifest(run, **kwargs)
    assert first.as_dict()["provenance"] != second.as_dict()["provenance"]
    assert first.fingerprint_input() == second.fingerprint_input()
    assert "provenance" not in first.fingerprint_input()


def test_set_lists_and_object_key_order_normalize_but_semantic_arrays_do_not(build):
    frozen = assemble(build)
    value = frozen.as_dict()
    for key in ("sources", "files"):
        value[key].reverse()
    for source in value["sources"]:
        source["resource_ids"].reverse()
    for key in ("contracts", "mappings", "severity", "code_files", "schema_files"):
        value["rules"][key].reverse()
    for contract in value["rules"]["contracts"]:
        contract["content"]["identity"]["resource_ids"].reverse()
    value = dict(reversed(list(value.items())))
    assert FrozenManifest(json.dumps(value)).fingerprint_input() == frozen.fingerprint_input()
    vehicle = next(c for c in value["rules"]["contracts"] if c["id"] == "syn_vic_vehicle")
    vehicle["content"]["identity"]["key"]["fields"].reverse()
    assert FrozenManifest(json.dumps(value)).fingerprint_input() != frozen.fingerprint_input()
    assert frozen.as_dict()["files"][0]["header"][0] == "Crash ID"


def test_new_code_bytes_require_a_new_manifest_and_leave_old_snapshot(build):
    first = assemble(build)
    target = build[1]["project_root"] / "sql/analysis.sql"
    target.write_text(target.read_text() + "-- changed query\n")
    with pytest.raises(IntakeError, match="differs"):
        freeze_manifest(first.as_dict(), project_root=build[1]["project_root"], inventory=build[1]["inventory"])
    second = assemble(build)
    assert first.fingerprint_input() != second.fingerprint_input()


def test_database_dependencies_are_hashed_and_require_refreezing(build):
    project = build[1]["project_root"]
    dependencies = ("requirements.txt", "requirements-dev.txt", "requirements-db.txt")
    for name in dependencies:
        shutil.copyfile(ROOT / name, project / name)
    build[1]["inventory"]["components"]["runner"].extend(dependencies)
    first = assemble(build)
    hashes = {entry["path"]: entry["sha256"] for entry in first.as_dict()["rules"]["code_files"]}
    for name in dependencies:
        assert hashes[name] == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()

    target = project / "requirements-db.txt"
    target.write_bytes(target.read_bytes() + b"\n# Changed dependency snapshot.\n")
    with pytest.raises(IntakeError) as caught:
        freeze_manifest(first.as_dict(), project_root=project, inventory=build[1]["inventory"])
    assert caught.value.code == "MANIFEST_VERSION_CHANGED"
    second = assemble(build)
    assert first.fingerprint_input() != second.fingerprint_input()
    assert next(entry["sha256"] for entry in first.as_dict()["rules"]["code_files"]
                if entry["path"] == "requirements-db.txt") == hashes["requirements-db.txt"]


@pytest.mark.parametrize("relative", [
    "arbitrary.txt", "requirements-extra.txt", "docs/requirements-db.txt",
    "raw_datasource/requirements-db.txt",
])
def test_dependency_allowlist_keeps_other_text_and_excluded_paths_blocked(build, relative):
    path = build[1]["project_root"] / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((ROOT / "requirements-db.txt").read_bytes())
    build[1]["inventory"]["components"]["runner"].append(relative)
    with pytest.raises(IntakeError) as caught:
        assemble(build)
    assert caught.value.code == "MANIFEST_INPUT"


def test_writes_new_history_only_and_enforces_kind_directory(build, tmp_path):
    frozen = assemble(build)
    path = tmp_path / "history/synthetic/manifests/first.json"
    assert frozen.write(path) == path
    before = path.read_bytes()
    assert read_json(path) == frozen.as_dict()
    with pytest.raises(FileExistsError):
        frozen.write(path)
    assert path.read_bytes() == before
    with pytest.raises(IntakeError):
        frozen.write(tmp_path / "official/manifests/other.json")


@pytest.mark.parametrize("component", COMPONENTS)
def test_missing_any_build_component_blocks(build, component):
    del build[1]["inventory"]["components"][component]
    with pytest.raises(IntakeError) as caught:
        assemble(build)
    assert caught.value.code == "MANIFEST_VERSION_MISSING"


@pytest.mark.parametrize("contents", ['{"id":1,"id":2}', '{"nested":{"a":1,"a":2}}',
                                      '{"n":NaN}', '{"n":Infinity}', '{"n":1.5}', '{"n":1e3}'])
def test_strict_json_rejects_duplicate_keys_and_numeric_decimals(tmp_path, contents):
    path = tmp_path / "invalid.json"
    path.write_text(contents)
    with pytest.raises(IntakeError):
        read_json(path)


@pytest.mark.parametrize("change", [
    lambda m: m.update(extra=True),
    lambda m: m["analysis"].update(year_from=True),
    lambda m: m["analysis"].update(year_to=2019),
    lambda m: m["sources"][0].update(source_id="official_nsw"),
    lambda m: m["sources"][0]["resource_ids"].pop(),
    lambda m: m["files"].pop(),
    lambda m: m["files"].append(deepcopy(m["files"][0])),
    lambda m: m["files"][0].update(raw_count=True),
    lambda m: m["files"][0].update(parser_version=""),
    lambda m: m["rules"]["contracts"].pop(),
    lambda m: m["rules"]["contracts"][0].update(status="draft"),
    lambda m: m["rules"]["contracts"][0].update(version=""),
    lambda m: m["rules"]["contracts"][0]["content"].pop("snapshot"),
    lambda m: m["rules"]["contracts"][0]["content"]["identity"].update(release_label="another release"),
    lambda m: m["rules"]["mappings"].pop(),
    lambda m: m["rules"]["mappings"][0].update(content={}),
    lambda m: m["rules"]["mappings"].append(deepcopy(m["rules"]["mappings"][0])),
    lambda m: m["rules"]["severity"].append(deepcopy(m["rules"]["severity"][0])),
    lambda m: m["rules"]["severity"].pop(),
    lambda m: m["rules"]["severity"].pop(0),
    lambda m: m["rules"]["severity"][0].update(definition_version="different"),
    lambda m: m["rules"]["qa_contract"].update(version=""),
    lambda m: m["rules"].update(schema_files=[]),
    lambda m: m["required_checks"].pop(),
    lambda m: m["required_checks"].reverse(),
    lambda m: m["provenance"].update(prepared_at="2026-09-19T10:00:00+10:00"),
    lambda m: m["provenance"]["files"][0].update(archive_relpath="official/archive/wrong"),
    lambda m: m["provenance"]["files"][0].update(download_url="https://name:secret@example.org/file.csv"),
    lambda m: m["rules"]["mappings"][0]["content"].update(rate=0.5),
    lambda m: m["rules"]["mappings"][0]["content"].update(rate=float("nan")),
    lambda m: m["rules"]["mappings"][0]["content"].update(batch_id="7d1be955-7653-414b-a302-bbd111bbc934"),
])
def test_incomplete_or_inconsistent_manifest_blocks(build, change):
    value = assemble(build).as_dict()
    change(value)
    with pytest.raises(IntakeError):
        validate_manifest(value)


def test_protocol_can_describe_runtime_fields_and_keep_decimal_strings(build):
    value = assemble(build).as_dict()
    value["rules"]["mappings"][0]["content"]["fields"] = {"raw_record_id": "UUID reference", "batch_id": "caller-supplied UUID"}
    value["rules"]["mappings"][0]["content"]["coordinate_limit"] = "90.0000000"
    validate_manifest(value)


@pytest.mark.parametrize("path", ["../outside.sql", "/tmp/absolute.sql", "sql/./fp1.sql",
                                  "docs/reference.sql", "artifacts/run.json", "notes.md", ".env"])
def test_rejects_non_build_inventory_paths(build, path):
    build[1]["inventory"]["components"]["fp1"] = [path]
    with pytest.raises(IntakeError):
        assemble(build)


def test_missing_file_and_lfs_pointer_are_not_code_versions(build):
    path = build[1]["project_root"] / "sql/fp1.sql"
    path.unlink()
    with pytest.raises(IntakeError) as caught:
        assemble(build)
    assert caught.value.code == "MANIFEST_VERSION_MISSING"
    path.write_text("version https://git-lfs.github.com/spec/v1\noid sha256:abc\n")
    with pytest.raises(IntakeError, match="LFS"):
        assemble(build)


def test_changed_native_archive_or_jsonl_is_rejected(build):
    file = read_json(build[0] / "files.json")["files"][0]
    path = build[0] / "records" / (file["resource_id"] + ".jsonl")
    path.write_bytes(path.read_bytes() + b"{}\n")
    with pytest.raises(IntakeError, match="record bytes"):
        assemble(build)


def test_files_json_alone_cannot_be_used_as_manifest(build):
    with pytest.raises(IntakeError):
        validate_manifest(read_json(build[0] / "files.json"))


def test_no_fixed_source_or_resource_count(build):
    value = assemble(build).as_dict()
    source_id, resource_id = "syn_act", "syn_act_crash"
    text = json.dumps(value).replace("syn_qld", source_id)
    value = json.loads(text)
    assert resource_id in [f["resource_id"] for f in value["files"]]
    validate_manifest(value)
    # A single independently selected source is also a valid resource set.
    value["sources"] = [s for s in value["sources"] if s["source_id"] == source_id]
    value["files"] = [f for f in value["files"] if f["source_id"] == source_id]
    value["rules"]["contracts"] = [c for c in value["rules"]["contracts"] if c["id"] == resource_id]
    value["rules"]["mappings"] = [m for m in value["rules"]["mappings"] if m["id"] == resource_id + "_mapping"]
    value["rules"]["severity"] = [s for s in value["rules"]["severity"] if s["source_id"] == source_id]
    value["provenance"]["files"] = [f for f in value["provenance"]["files"] if f["resource_id"] == resource_id]
    validate_manifest(value)


def test_can_add_a_fourth_source_without_changing_core_code(build):
    value = assemble(build).as_dict()
    for key, field in (("sources", "source_id"), ("files", "source_id")):
        selected = [item for item in value[key] if item[field] == "syn_qld"]
        value[key].extend(json.loads(json.dumps(selected).replace("syn_qld", "syn_act")))
    for key, field, match in (("contracts", "id", "syn_qld_crash"),
                              ("mappings", "id", "syn_qld_crash_mapping"),
                              ("severity", "source_id", "syn_qld")):
        selected = [item for item in value["rules"][key] if item[field] == match]
        value["rules"][key].extend(json.loads(json.dumps(selected).replace("syn_qld", "syn_act")))
    selected = [p for p in value["provenance"]["files"] if p["resource_id"] == "syn_qld_crash"]
    value["provenance"]["files"].extend(json.loads(json.dumps(selected).replace("syn_qld", "syn_act")))
    assert len(value["sources"]) == 4 and len(value["files"]) == 8
    validate_manifest(value)


def test_origins_are_required_and_official_confirmation_is_not_inferred(build):
    del build[1]["origins"]["syn_vic_node"]
    with pytest.raises(IntakeError):
        assemble(build)


def test_official_mode_requires_recorded_review_and_download_urls(build):
    value = assemble(build).as_dict()
    value = json.loads(json.dumps(value).replace("syn_", "official_").replace('"synthetic"', '"official"'))
    for file in value["provenance"]["files"]:
        file["archive_relpath"] = file["archive_relpath"].replace("synthetic/", "official/", 1)
        file["download_url"] = "https://example.org/input.csv"
    for contract in value["rules"]["contracts"]:
        contract["status"] = "confirmed"
        contract["content"]["confirmation"] = {
            "status": "confirmed", "owner": "test owner", "reviewed_by": "test reviewer",
            "licence": "test licence", "checked_at": "2026-09-19", "unresolved": [],
            "references": ["Unit-test metadata only; not official approval."],
        }
    validate_manifest(value)
    value["rules"]["contracts"][0]["content"]["confirmation"].pop("reviewed_by")
    with pytest.raises(IntakeError):
        validate_manifest(value)


def test_reads_shared_qa_section_verbatim(tmp_path):
    section = read_json(ROOT / "config/qa-team-v1.1.json")["content"]["text"] + "\n"
    path = tmp_path / "team.md"
    path.write_text("协作合同 v1.1\n## 3. QA具体对象与发布门槛\n" + section + "## 4. S0\nExcluded.\n")
    contract = team_qa_contract(path)
    assert contract["content"]["text"] == section.strip()
    assert "Excluded" not in contract["content"]["text"]


def test_incomplete_qa_text_and_mode_symlink_block(build, tmp_path):
    frozen = assemble(build)
    value = frozen.as_dict()
    value["rules"]["qa_contract"]["content"]["text"] = "QA01_INPUT: pending"
    with pytest.raises(IntakeError, match="complete agreed"):
        validate_manifest(value)
    root = tmp_path / "history"
    (root / "official").mkdir(parents=True)
    (root / "synthetic").symlink_to(root / "official", target_is_directory=True)
    with pytest.raises(IntakeError, match="symlinks"):
        frozen.write(root / "synthetic/manifests/first.json")
    assert not list((root / "official").iterdir())
