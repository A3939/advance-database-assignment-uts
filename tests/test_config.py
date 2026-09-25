"""Tests for valid catalogues and configuration errors."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from arsia_ingest.config import load_config
from arsia_ingest.models import IntakeError


def catalogue() -> dict:
    return {
        "config_version": "intake-v1",
        "dataset_kind": "synthetic",
        "resources": [{
            "source_id": "syn_test", "resource_id": "syn_crash",
            "resource_role": "crash", "entity_kind": "crash",
            "path": "../input.csv", "format": "csv",
            "header": ["ID", "Value"], "encoding": "utf-8",
            "sheet": None, "header_row": 1,
        }],
    }


def save(tmp_path: Path, data: object) -> Path:
    folder = tmp_path / "config"
    folder.mkdir(exist_ok=True)
    path = folder / "inputs.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_relative_paths_are_relative_to_catalogue_not_working_directory(tmp_path, monkeypatch):
    path = save(tmp_path, catalogue())
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    result = load_config(path)
    assert result.dataset_kind == "synthetic"
    assert result.config_path == path.resolve()
    assert result.resources[0].path == tmp_path / "input.csv"
    assert result.resources[0].header == ("ID", "Value")
    assert result.resources[0].expected_sha256 is None
    # The file can be missing here: load_config only validates the catalogue.
    assert not result.resources[0].path.exists()


def test_absolute_paths_and_meaningful_header_whitespace_are_preserved(tmp_path):
    data = catalogue()
    source = tmp_path / "raw input.csv"
    data["resources"][0].update(path=str(source), header=[" ID ", "Value"])
    result = load_config(save(tmp_path, data))
    assert result.resources[0].path == source
    assert result.resources[0].header == (" ID ", "Value")


@pytest.mark.parametrize("field,value,code", [
    ("config_version", "intake-v2", "CONFIG_VERSION"),
    ("dataset_kind", "production", "CONFIG_DATASET_KIND"),
    ("dataset_kind", [], "CONFIG_DATASET_KIND"),
    ("resources", [], "CONFIG_RESOURCES"),
    ("resources", {}, "CONFIG_RESOURCES"),
])
def test_invalid_root_values_are_rejected(tmp_path, field, value, code):
    data = catalogue()
    data[field] = value
    with pytest.raises(IntakeError) as error:
        load_config(save(tmp_path, data))
    assert error.value.code == code


@pytest.mark.parametrize("location,field", [
    ("root", "analysis"), ("resource", "parser_version"),
    ("resource", "locator_version"), ("resource", "raw_count"),
])
def test_unknown_fields_cannot_silently_change_parser_contract(tmp_path, location, field):
    data = catalogue()
    target = data if location == "root" else data["resources"][0]
    target[field] = "unapproved extension"
    with pytest.raises(IntakeError, match="fields") as error:
        load_config(save(tmp_path, data))
    assert error.value.code == "CONFIG_FIELDS"
    assert field in error.value.details["unknown"]


@pytest.mark.parametrize("location,field", [
    ("root", "config_version"), ("root", "dataset_kind"),
    ("resource", "resource_id"), ("resource", "encoding"),
    ("resource", "sheet"), ("resource", "header_row"),
])
def test_required_fields_cannot_be_implicitly_defaulted(tmp_path, location, field):
    data = catalogue()
    target = data if location == "root" else data["resources"][0]
    del target[field]
    with pytest.raises(IntakeError) as error:
        load_config(save(tmp_path, data))
    assert error.value.code == "CONFIG_FIELDS"
    assert field in error.value.details["missing"]


@pytest.mark.parametrize("field,value,code", [
    ("resource_id", "../syn_crash", "CONFIG_NAMESPACE"),
    ("resource_id", "syn_crash/other", "CONFIG_NAMESPACE"),
    ("resource_id", "syn_事故", "CONFIG_NAMESPACE"),
    ("resource_id", "syn_", "CONFIG_NAMESPACE"),
    ("source_id", "official_test", "CONFIG_NAMESPACE"),
    ("resource_id", "official_crash", "CONFIG_NAMESPACE"),
    ("source_id", "1syn_test", "CONFIG_NAMESPACE"),
    ("source_id", "syn_test\x00", "CONFIG_TYPE"),
    ("resource_role", "  ", "CONFIG_TYPE"),
    ("entity_kind", "person", "CONFIG_ENTITY_KIND"),
    ("path", "", "CONFIG_TYPE"),
    ("path", 123, "CONFIG_TYPE"),
    ("format", "json", "CONFIG_FORMAT"),
    ("header_row", True, "CONFIG_HEADER_ROW"),
    ("header_row", 1.0, "CONFIG_HEADER_ROW"),
    ("header_row", 2, "CONFIG_HEADER_ROW"),
    ("header", [], "CONFIG_HEADER"),
    ("header", ["ID", "ID"], "CONFIG_HEADER"),
    ("header", ["ID", None], "CONFIG_TYPE"),
    ("header", ["ID", ""], "CONFIG_TYPE"),
    ("header", "ID,Value", "CONFIG_HEADER"),
    ("encoding", "latin-1", "CONFIG_CSV"),
    ("encoding", "utf-8-sig", "CONFIG_CSV"),
    ("sheet", "Sheet1", "CONFIG_CSV"),
    ("expected_sha256", "A" * 64, "CONFIG_HASH"),
    ("expected_sha256", "a" * 63, "CONFIG_HASH"),
    ("expected_sha256", 123, "CONFIG_HASH"),
])
def test_invalid_resource_contracts_are_rejected(tmp_path, field, value, code):
    data = catalogue()
    data["resources"][0][field] = value
    with pytest.raises(IntakeError) as error:
        load_config(save(tmp_path, data))
    assert error.value.code == code


def test_duplicate_resource_ids_are_rejected_even_across_sources(tmp_path):
    data = catalogue()
    duplicate = copy.deepcopy(data["resources"][0])
    duplicate["source_id"] = "syn_other_source"
    data["resources"].append(duplicate)
    with pytest.raises(IntakeError) as error:
        load_config(save(tmp_path, data))
    assert error.value.code == "CONFIG_DUPLICATE_RESOURCE"


@pytest.mark.parametrize("document", [
    '{"config_version":"intake-v1","config_version":"intake-v1"}',
    '{"resources":[{"source_id":"syn_a","source_id":"syn_b"}]}',
])
def test_duplicate_json_keys_are_rejected_at_every_depth(tmp_path, document):
    path = tmp_path / "duplicate.json"
    path.write_text(document, encoding="utf-8")
    with pytest.raises(IntakeError) as error:
        load_config(path)
    assert error.value.code == "CONFIG_DUPLICATE_KEY"


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_numbers_are_rejected(tmp_path, token):
    path = tmp_path / "nonfinite.json"
    path.write_text('{"dataset_kind":' + token + '}', encoding="utf-8")
    with pytest.raises(IntakeError) as error:
        load_config(path)
    assert error.value.code == "CONFIG_NONFINITE"


@pytest.mark.parametrize("contents", [b"not JSON", b'{"bad":"\xff"}', b"[]"])
def test_unreadable_or_nonobject_config_is_structured_error(tmp_path, contents):
    path = tmp_path / "invalid.json"
    path.write_bytes(contents)
    with pytest.raises(IntakeError) as error:
        load_config(path)
    assert error.value.code in {"CONFIG_READ", "CONFIG_TYPE"}


def test_missing_config_is_structured_error(tmp_path):
    with pytest.raises(IntakeError) as error:
        load_config(tmp_path / "missing.json")
    assert error.value.code == "CONFIG_READ"


@pytest.mark.parametrize("encoding,sheet", [("utf-8", "Data"), (None, None), (None, "")])
def test_xlsx_requires_named_sheet_and_null_encoding(tmp_path, encoding, sheet):
    data = catalogue()
    data["resources"][0].update(format="xlsx", path="../input.xlsx", encoding=encoding, sheet=sheet)
    with pytest.raises(IntakeError) as error:
        load_config(save(tmp_path, data))
    assert error.value.code == "CONFIG_XLSX"


def test_xlsx_contract_and_file_hash_are_loaded(tmp_path):
    data = catalogue()
    data["resources"][0].update(
        format="xlsx", path="../input.xlsx", encoding=None, sheet="Data",
        expected_sha256="a" * 64,
    )
    result = load_config(save(tmp_path, data)).resources[0]
    assert result.sheet == "Data"
    assert result.encoding is None
    assert result.expected_sha256 == "a" * 64
    assert result.parser_version == "xlsx-native-v1"
    assert result.locator_version == "xlsx-physical-v1"


def test_official_namespace_and_unbounded_source_count(tmp_path):
    data = catalogue()
    data["dataset_kind"] = "official"
    data["resources"] = []
    for name in ("nsw", "vic", "qld", "sa"):
        spec = catalogue()["resources"][0]
        spec.update(source_id=f"official_{name}", resource_id=f"official_{name}_crash")
        data["resources"].append(spec)
    result = load_config(save(tmp_path, data))
    assert len(result.resources) == 4
    assert result.resources[-1].source_id == "official_sa"


def test_xlsx_sheet_rejects_nul_before_creating_run(tmp_path):
    data = catalogue()
    data["resources"][0].update(format="xlsx", path="../input.xlsx", encoding=None, sheet="Data\x00")
    with pytest.raises(IntakeError) as error:
        load_config(save(tmp_path, data))
    assert error.value.code == "CONFIG_TYPE"


def test_case_only_resource_ids_cannot_collide_on_case_insensitive_filesystems(tmp_path):
    data = catalogue()
    duplicate = copy.deepcopy(data["resources"][0])
    duplicate["resource_id"] = "syn_CRASH"
    data["resources"].append(duplicate)
    with pytest.raises(IntakeError) as error:
        load_config(save(tmp_path, data))
    assert error.value.code == "CONFIG_DUPLICATE_RESOURCE"


@pytest.mark.parametrize("field,value", [
    ("resource_role", "crash\ud800"), ("header", ["ID", "\ud800"]),
])
def test_escaped_lone_surrogate_is_rejected_before_utf8_receipt_generation(tmp_path, field, value):
    data = catalogue()
    data["resources"][0][field] = value
    path = tmp_path / "invalid-unicode.json"
    # The file is valid UTF-8, but this JSON escape decodes to an invalid character.
    path.write_text(json.dumps(data, ensure_ascii=True), encoding="utf-8")
    with pytest.raises(IntakeError) as error:
        load_config(path)
    assert error.value.code == "CONFIG_TYPE"
