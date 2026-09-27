"""Short-form parent fields keep the same real PostgreSQL lineage checks."""

import json

import pytest

from arsia_d04 import reconcile
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.runner import ModuleConnection, RunEvidence
from test_d04_lineage_postgres import (
    connection, prepared, frozen, isolated, pytestmark,
    load, select_fault, inject,
)


@pytest.mark.parametrize("wrong_parent", [False, True])
def test_synthetic_node_short_form_keeps_selected_parent_check(
    connection, prepared, frozen, wrong_parent,
):
    context = load(connection, prepared, frozen)
    assert isinstance(frozen, FrozenManifest)
    value = frozen.as_dict()
    node = next(c for c in value["rules"]["contracts"] if c["id"] == "syn_vic_node")
    # S0's normal explicit mapping also checks Node ID. This separate synthetic
    # variant checks the same crash key on both sides, as the official short form does.
    parent = node["content"]["identity"]["parent"]
    parent["fields"] = parent["parent_fields"] = ["ACCIDENT_NO"]
    explicit = FrozenManifest(json.dumps(value))
    target_fields = parent.pop("parent_fields")
    assert target_fields == ["ACCIDENT_NO"]
    shortened = FrozenManifest(json.dumps(value))
    before = shortened.as_dict()
    if wrong_parent:
        target, wrong, _ = select_fault(connection, context, "node", "syn_vic")
        original_accident = connection.execute("SELECT payload->>'ACCIDENT_NO' FROM raw.record WHERE raw_record_id=%s",
                                               (target["raw_record_id"],)).fetchone()[0]
        assert wrong["payload"]["ACCIDENT_NO"] != original_accident
        inject(connection, context, target, wrong, "node")
    # The two equivalent contracts query the same synthetic component state.
    reports = [reconcile(ModuleConnection(connection), context.batch_id, manifest.as_dict(),
                         evidence=RunEvidence(context.evidence.directory / name))
               for manifest, name in [(explicit, "explicit-parent"), (shortened, "short-parent")]]
    def results(report):
        return [(row["object_key"], row["result"], row["affected_count"], row["actual"], row["expected"])
                for row in report.rows]
    assert results(reports[0]) == results(reports[1])
    assert shortened.as_dict() == before
    report = reports[1]
    concrete = [row for row in report.rows if row["object_key"] != "batch"]
    assert len(concrete) == 15
    blocked = [row for row in concrete if row["result"] == "block"]
    if wrong_parent:
        assert len(blocked) == 1
        assert blocked[0]["object_key"] == f"source_year:syn_vic:{target['occurrence_year']}"
        assert blocked[0]["actual"]["metrics"]["lineage_error_count"] == 1
    else:
        assert not blocked and all(row["result"] == "pass" for row in report.rows)
    assert connection.info.transaction_status.name == "INTRANS"
