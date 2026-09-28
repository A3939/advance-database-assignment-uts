"""The optional AT10 rule applies only to declared synthetic NSW inputs."""
import json

import pytest

from arsia_c.projections.nsw import _parameters
from test_c03_nsw_projection import component_manifest


def manifest(kind="synthetic"):
    value = component_manifest()
    if kind == "official":
        value = json.loads(json.dumps(value).replace("syn_", "official_"))
        value["dataset_kind"] = kind
        for contract in value["rules"]["contracts"]:
            contract["status"] = "confirmed"
        mapping = value["rules"]["mappings"][0]
        mapping["content"]["native_severity_codes"] = {"F": "F", "I": "I", "N": "N"}
    return value


def test_default_missing_values_remain_unknown():
    for kind in ("synthetic", "official"):
        p = _parameters(manifest(kind), "unused")
        assert p["missing_severity"] is None and p["missing_severity_rule"] is None


def test_declared_synthetic_override_keeps_source_severity_definition():
    value = manifest()
    mapping = value["rules"]["mappings"][0]
    mapping["version"] = "syn-at10-v2"
    mapping["content"].update(missing_severity_code="N", missing_severity_reason="AT10 fictitious rule.")
    p = _parameters(value, "unused")
    assert json.loads(p["missing_severity"]) == {"code": "N", "fatal": False}
    assert json.loads(p["missing_severity_rule"])["mapping_version"] == "syn-at10-v2"
    assert all(s["is_fatal_crash"] is None for s in value["rules"]["severity"]
               if s["severity_code"] == "__MISSING__")


@pytest.mark.parametrize("change", [
    {"missing_severity_code": "N"}, {"missing_severity_reason": "Missing code"},
    {"missing_severity_code": "N", "missing_severity_reason": " "},
    {"missing_severity_code": "X", "missing_severity_reason": "Undefined"},
    {"missing_severity_code": "__MISSING__", "missing_severity_reason": "Still unknown"},
    {"missing_severity_code": ["N"], "missing_severity_reason": "Wrong type"},
])
def test_incomplete_override_is_rejected(change):
    value = manifest()
    value["rules"]["mappings"][0]["content"].update(change)
    with pytest.raises(ValueError, match="missing severity override"):
        _parameters(value, "unused")


def test_official_override_is_rejected():
    value = manifest("official")
    value["rules"]["mappings"][0]["content"].update(
        missing_severity_code="N", missing_severity_reason="Cannot change official unknowns.")
    with pytest.raises(ValueError, match="missing severity override"):
        _parameters(value, "unused")
