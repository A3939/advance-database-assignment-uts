"""Installed C/D code and partial inventory must agree."""

import hashlib
import importlib
from importlib.resources import files
import os
from pathlib import Path
import sys

import pytest

from arsia_ingest.components import BINDING_SPECS
from arsia_ingest.manifest import FrozenManifest, freeze_manifest
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import BuildModules, ModuleBinding
from cd_support import ROOT, bindings, fragment, interface_manifest, inventory


def test_real_paths_hashes_and_dependencies():
    value = fragment()
    assert value["final_platform"] is False
    assert set(value["components"]) == {"project", "vault", "canonical", "dw", "qa"}
    paths = {p for group in value["components"].values() for p in group}
    paths.update(value["interface_code_paths"])
    assert paths == {entry["path"] for entry in value["code_files"]}
    migrations = {str(p.relative_to(ROOT)) for p in (ROOT / "sql/migrations").glob("*.sql")}
    assert migrations == {entry["path"] for entry in value["schema_files"]}
    assert len(migrations) == 11 and not migrations.intersection(paths)
    for entry in value["code_files"] + value["schema_files"]:
        assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    assert value["dependencies"]["new_external_packages"] == []


def test_installed_resources_match_inventory():
    for entry in fragment()["code_files"]:
        path = Path(entry["path"])
        if path.parts[0] != "src":
            continue
        package = path.parts[1]
        data = files(package).joinpath(*path.parts[2:]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        if os.environ.get("AC_REQUIRE_INSTALLED"):
            installed = Path(importlib.import_module(package).__file__).resolve()
            assert installed.is_relative_to(Path(sys.prefix).resolve())
            assert not installed.is_relative_to(ROOT)


def test_real_bindings_do_not_supply_c10_or_publication():
    selected = bindings()
    declared = fragment()
    assert set(selected) == {"project", "vault", "canonical", "dw", "qa_d"}
    for stage, binding in selected.items():
        expected = declared["bindings"][stage]
        assert (expected["callback"], expected["code_path"], expected["version"]) == BINDING_SPECS[stage]
        module, name = expected["callback"].split(":")
        assert binding.callback is getattr(importlib.import_module(module), name)
        assert type(binding) is ModuleBinding
        assert binding.code_path == expected["code_path"]
        assert binding.version == expected["version"]
        component = "qa" if stage == "qa_d" else stage
        assert binding.code_path in declared["components"][component]
    modules = BuildModules(**selected)
    assert modules.qa_c is None and modules.publish is None


def test_real_frozen_interface_preserves_missing_platform_boundary(tmp_path):
    result = prepare(ROOT / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert result["status"] == "prepared" and result["raw_count"] == 19
    frozen = interface_manifest(result["run_dir"])
    assert type(frozen) is FrozenManifest
    value = frozen.as_dict()
    assert len(value["sources"]) == 3 and len(value["rules"]["severity"]) == 12
    assert value["rules"]["code_files"] == fragment()["code_files"]
    assert value["rules"]["schema_files"] == fragment()["schema_files"]
    with pytest.raises(IntakeError) as error:
        freeze_manifest(value, project_root=ROOT, inventory=inventory())
    assert error.value.code == "MANIFEST_VERSION_MISSING"
