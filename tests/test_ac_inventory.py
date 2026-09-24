"""Check the installed modules and the partial inventory boundary."""

import hashlib
import importlib
from importlib.resources import files
import os
from pathlib import Path
import sys

import pytest

from arsia_ingest.manifest import FrozenManifest, freeze_manifest
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import BuildModules, ModuleBinding
from ac_support import ROOT, bindings, fragment, interface_manifest, inventory


def digest(data):
    return hashlib.sha256(data).hexdigest()


def test_inventory_hashes_cover_runtime_code_and_all_migrations():
    value = fragment()
    assert value["final_platform"] is False
    assert set(value["components"]) == {"project", "vault", "canonical", "dw"}
    paths = {p for group in value["components"].values() for p in group}
    paths.update(value["interface_code_paths"])
    code = {entry["path"]: entry["sha256"] for entry in value["code_files"]}
    assert set(code) == paths
    schema = {entry["path"] for entry in value["schema_files"]}
    assert schema == {str(p.relative_to(ROOT)) for p in (ROOT / "sql/migrations").glob("*.sql")}
    assert len(schema) == 11 and not schema.intersection(code)
    for entry in value["code_files"] + value["schema_files"]:
        assert digest((ROOT / entry["path"]).read_bytes()) == entry["sha256"]
    assert len(value["path_moves"]) == 9
    for moved in value["path_moves"]:
        assert moved["upstream_path"] == "sql/projections/" + Path(moved["path"]).name
        assert moved["path"].startswith("src/arsia_c/projections/sql/")
        assert code[moved["path"]] == moved["sha256"]


def test_installed_python_and_sql_match_the_inventory():
    for entry in fragment()["code_files"]:
        path = Path(entry["path"])
        if path.parts[0] != "src":
            continue
        package = path.parts[1]
        resource = files(package).joinpath(*path.parts[2:])
        assert digest(resource.read_bytes()) == entry["sha256"]
        if os.environ.get("AC_REQUIRE_INSTALLED"):
            installed = Path(importlib.import_module(package).__file__).resolve()
            assert installed.is_relative_to(Path(sys.prefix).resolve())
            assert not installed.is_relative_to(ROOT)


def test_bindings_use_real_callbacks_and_keep_missing_stages_unset():
    declared = fragment()
    selected = bindings()
    assert set(selected) == {"project", "vault", "canonical", "dw"}
    for stage, binding in selected.items():
        assert type(binding) is ModuleBinding and callable(binding.callback)
        assert binding.code_path in declared["components"][stage]
        assert binding.version == declared["bindings"][stage]["version"]
    modules = BuildModules(**selected)
    assert modules.qa_c is None and modules.qa_d is None and modules.publish is None


def test_real_frozen_manifest_does_not_bypass_full_inventory(tmp_path):
    prepared = prepare(ROOT / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert prepared["status"] == "prepared" and prepared["raw_count"] == 19
    frozen = interface_manifest(prepared["run_dir"])
    assert type(frozen) is FrozenManifest
    value = frozen.as_dict()
    assert len(value["sources"]) == 3 and len(value["rules"]["severity"]) == 12
    assert value["rules"]["schema_files"] == fragment()["schema_files"]
    value["rules"]["severity"].clear()
    assert len(frozen.as_dict()["rules"]["severity"]) == 12
    with pytest.raises(IntakeError) as error:
        freeze_manifest(frozen.as_dict(), project_root=ROOT, inventory=inventory())
    assert error.value.code == "MANIFEST_VERSION_MISSING"
