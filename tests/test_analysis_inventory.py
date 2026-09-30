"""Installed D05-D08 resources and B's partial analysis inventory."""
import hashlib
import importlib
from importlib.resources import files
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_analysis_paths_hashes_and_real_bindings():
    value = json.loads((ROOT / "config/analysis-inventory.json").read_text())
    assert value["final_platform"] is False and value["complete_analysis"] is False
    assert set(value["components"]) == {"analysis"}
    assert set(value["components"]["analysis"]) == {r["path"] for r in value["code_files"]}
    assert value["dependencies"]["new_external_packages"] == []
    for entry in value["code_files"] + value["schema_files"]:
        assert hashlib.sha256((ROOT/entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    for binding in value["bindings"].values():
        module, name = binding["python"].split(":")
        installed = importlib.import_module(module)
        assert callable(getattr(installed, name))
        assert installed.QUERY_VERSION == binding["version"]


def test_installed_analysis_sql_matches_declared_bytes():
    value = json.loads((ROOT / "config/analysis-inventory.json").read_text())
    for name in value["bindings"]:
        module = importlib.import_module("arsia_"+name)
        sql = module.install_sql().encode("utf-8")
        path = next(p for p in value["deployment"]["sql_files"] if "/arsia_"+name+"/" in p)
        assert sql == (ROOT/path).read_bytes()
        assert sql == files("arsia_"+name).joinpath("sql",Path(path).name).read_bytes()
        if os.environ.get("AC_REQUIRE_INSTALLED"):
            assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
            assert not Path(module.__file__).resolve().is_relative_to(ROOT)
