"""D02 packaging, B definitions and inventory boundaries."""
from copy import deepcopy
import importlib
import os
from pathlib import Path
import sys

import pytest

from arsia_d02 import DimensionContractError, build_dimension_rows, runner_callback
from arsia_ingest.manifest import FrozenManifest, freeze_manifest
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import BuildModules, ModuleBinding
from d02_support import ROOT, definitions, digest, fragment, interface_manifest, partial_inventory

BATCH = "12345678-1234-5678-9234-567812345678"


def test_real_s0_definitions_include_all_months_and_categories():
    value = definitions()
    rows = build_dimension_rows(value, BATCH)
    assert rows.counts() == {"dim_source": 3, "dim_month": 60, "dim_severity": 12}
    assert rows.months == tuple((year * 100 + month, year, month)
                               for year in range(2020, 2025) for month in range(1, 13))
    assert {r[1] for r in rows.sources} == {"syn_nsw", "syn_vic", "syn_qld"}
    for source in value["sources"]:
        assert {r[2] for r in rows.severities if r[1] == source["source_id"]} == {"F", "I", "N", "__MISSING__"}


@pytest.mark.parametrize("case,code", [
    ("duplicate", "D02_SEVERITY_DUPLICATE"),
    ("missing", "D02_MISSING_CATEGORY"),
    ("years", "D02_ANALYSIS_RANGE"),
])
def test_invalid_definitions_still_block(case, code):
    value = definitions()
    if case == "duplicate":
        value["severity"].append(deepcopy(value["severity"][0]))
    elif case == "missing":
        value["severity"] = [s for s in value["severity"] if s["severity_code"] != "__MISSING__"]
    else:
        value["analysis"] = {"year_from": 2024, "year_to": 2020}
    with pytest.raises(DimensionContractError) as error:
        build_dimension_rows(value, BATCH)
    assert error.value.code == code


def test_inventory_hashes_imports_and_binding_match_installed_code():
    value = fragment()
    assert value["complete_dw"] is False
    assert {f["path"] for f in value["code_files"]} == set(value["components"]["dw"])
    for entry in value["code_files"]:
        assert digest(ROOT / entry["path"]) == entry["sha256"]
        if entry["path"].startswith("src/"):
            name = entry["path"][4:-3].replace("/", ".").removesuffix(".__init__")
            installed = Path(importlib.import_module(name).__file__).resolve()
            assert digest(installed) == entry["sha256"]
            if os.environ.get("D02_REQUIRE_INSTALLED"):
                assert installed.is_relative_to(Path(sys.prefix).resolve())
                assert not installed.is_relative_to(ROOT)
    module, function = value["binding"]["callback"].split(":")
    callback = getattr(importlib.import_module(module), function)
    binding = ModuleBinding(callback, value["binding"]["code_path"], value["binding"]["version"])
    assert binding.callback is runner_callback
    assert binding.code_path in value["components"]["dw"]
    assert binding.version == "d02-0.1.0-e4fbefa"
    assert BuildModules().dw is None


def test_real_frozen_object_uses_rules_severity_but_full_freeze_blocks(tmp_path):
    prepared = prepare(ROOT / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert prepared["status"] == "prepared" and prepared["raw_count"] == 19
    frozen = interface_manifest(prepared["run_dir"])
    assert type(frozen) is FrozenManifest
    before = frozen.as_dict()
    assert build_dimension_rows(before, BATCH) == build_dimension_rows(definitions(), BATCH)
    before["rules"]["severity"].clear()
    assert len(frozen.as_dict()["rules"]["severity"]) == 12
    with pytest.raises(IntakeError) as error:
        freeze_manifest(frozen.as_dict(), project_root=ROOT, inventory=partial_inventory())
    assert error.value.code == "MANIFEST_VERSION_MISSING"
