"""Frozen manifest admission, before any database writes."""

from copy import deepcopy
import pytest
from c45_support import state_manifest
from arsia_c.projections.source_contracts import (
    parameters,
    vic_definitions,
    qld_definitions,
)


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_s0_manifest_supported(state):
    assert parameters(state_manifest(state), "unused", state)["map_enabled"]


@pytest.mark.parametrize("state", ["VIC", "QLD"])
@pytest.mark.parametrize(
    "mutation",
    [
        "draft",
        "hash",
        "parser",
        "release",
        "mapping",
        "duplicates",
        "namespace",
        "counts",
        "year",
        "severity",
        "crs",
    ],
)
def test_invalid_contract_cannot_reach_sql(state, mutation):
    m = state_manifest(state)
    c = m["rules"]["contracts"][0]
    if mutation == "draft":
        c["status"] = "draft"
    elif mutation == "hash":
        m["files"][0]["file_sha256"] = "f" * 64
    elif mutation == "parser":
        m["files"][0]["parser_version"] = "other-v1"
    elif mutation == "release":
        c["content"]["identity"]["release_scope"] = "wrong"
    elif mutation == "mapping":
        m["rules"]["mappings"][0]["content"]["fatality_count"] = "wrong"
    elif mutation == "duplicates":
        m["rules"]["contracts"].append(deepcopy(c))
    elif mutation == "namespace":
        m["dataset_kind"] = "official"
    elif mutation == "counts":
        m["files"][0]["raw_count"] = True
    elif mutation == "year":
        m["analysis"]["year_from"] = True
    elif mutation == "severity":
        m["rules"]["severity"][0]["definition_version"] = "wrong"
    elif mutation == "crs":
        m["rules"]["mappings"][0]["content"]["location"]["crs"] = "EPSG:3857"
    with pytest.raises(ValueError):
        parameters(m, "unused", state)


def official_manifest(state):
    d = vic_definitions() if state == "VIC" else qld_definitions()
    return {
        "dataset_kind": "official",
        "analysis": d["analysis"],
        "sources": d["sources"],
        "files": [deepcopy(c["content"]["input"]) for c in d["contracts"]],
        "rules": {
            **{k: d[k] for k in ("contracts", "mappings", "severity")},
            "qa_contract": {
                "version": "team-v1.1-vic-r1" if state == "VIC" else "team-v1.1"
            },
        },
    }


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_adopted_official_definitions_disable_map(state):
    assert not parameters(official_manifest(state), "unused", state)["map_enabled"]


@pytest.mark.parametrize("state", ["VIC", "QLD"])
@pytest.mark.parametrize(
    "part", ["mapping", "confirmation", "source", "analysis", "severity"]
)
def test_official_scope_cannot_silently_expand(state, part):
    m = official_manifest(state)
    if part == "mapping":
        m["rules"]["mappings"][0]["content"]["allow_everything"] = True
    elif part == "confirmation":
        m["rules"]["contracts"][0]["content"]["confirmation"]["unresolved"] = [
            "new blocker"
        ]
    elif part == "source":
        m["sources"][0]["release_scope"] = "replacement"
    elif part == "analysis":
        m["analysis"]["year_to"] = 2025
    elif part == "severity":
        m["rules"]["severity"][0]["is_fatal_crash"] = False
    with pytest.raises(ValueError):
        parameters(m, "unused", state)


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_autocommit_is_rejected_without_any_sql(state):
    from arsia_c.projections.source_contracts import stage

    class Connection:
        autocommit = True

        def cursor(self):
            raise AssertionError("Must reject before SQL")

    with pytest.raises(ValueError, match="transaction"):
        stage(Connection(), parameters(state_manifest(state), "unused", state))


def test_node_crs_must_agree_with_crash_declaration():
    m = state_manifest("VIC")
    next(x for x in m["rules"]["mappings"] if x["id"] == "syn_vic_node_mapping")[
        "content"
    ]["location"]["crs"] = None
    with pytest.raises(ValueError, match="Node location"):
        parameters(m, "unused", "VIC")


def test_c09_accepts_exact_restricted_vic_parent_convention():
    from arsia_c.canonical_validation import selected_contracts

    result = selected_contracts(official_manifest("VIC"))
    unit = next(f for f in result if f["entity_kind"] == "unit")
    assert unit["parent_fields"] == unit["parent_crash_fields"] == ["ACCIDENT_NO"]


@pytest.mark.parametrize("change", ["status", "policy", "file", "year", "protocol"])
def test_c09_does_not_broaden_restricted_admission(change):
    from arsia_c.canonical_validation import selected_contracts
    from arsia_ingest.models import IntakeError

    m = official_manifest("VIC")
    if change == "status":
        for c in m["rules"]["contracts"]:
            c["status"] = "confirmed"
    elif change == "policy":
        m["rules"]["mappings"][0]["content"]["publisher_bundle_confirmed"] = True
    elif change == "file":
        m["files"][0]["file_sha256"] = "f" * 64
    elif change == "year":
        m["analysis"]["year_to"] = 2025
    elif change == "protocol":
        m["rules"]["qa_contract"]["version"] = "team-v1.1"
    with pytest.raises(IntakeError):
        selected_contracts(m)
