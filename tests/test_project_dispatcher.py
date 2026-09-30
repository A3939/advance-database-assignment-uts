"""Dispatcher selection tests use real FrozenManifest and RunContext objects."""

from dataclasses import replace
import json
from uuid import uuid4

import pytest

from arsia_c.projections import dispatcher
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import ModuleConnection, RunContext, RunEvidence
from cd_support import ROOT, interface_manifest


class Transaction:
    autocommit = False

    def cursor(self):
        raise AssertionError("Selection rejection should not query the database")


@pytest.fixture
def context(tmp_path):
    prepared = prepare(ROOT / "tests/fixtures/s0/config.json", tmp_path / "intake")
    frozen = interface_manifest(prepared["run_dir"])
    return RunContext(
        run_id="dispatch-test", dataset_kind="synthetic", batch_id=uuid4(),
        input_fingerprint="a" * 64, previous_batch_id=None, manifest=frozen,
        evidence=RunEvidence(tmp_path / "evidence"),
    )


def test_all_sources_receive_the_original_b_context(monkeypatch, context):
    called = []
    connection = ModuleConnection(Transaction())
    for state, module in (("NSW", dispatcher.nsw), ("VIC", dispatcher.vic), ("QLD", dispatcher.qld)):
        def callback(received_connection, received_context, state=state):
            assert received_connection is connection and received_context is context
            assert type(received_context.manifest) is FrozenManifest
            called.append(state)
        monkeypatch.setattr(module, "project", callback)
    assert dispatcher.project(connection, context) == {"project_source_count": 3}
    assert called == ["NSW", "VIC", "QLD"]
    evidence = json.loads((context.evidence.directory / "project-dispatch.json").read_text())
    assert evidence["batch_id"] == str(context.batch_id)
    assert [source["source_id"] for source in evidence["sources"]] == ["syn_nsw", "syn_vic", "syn_qld"]
    assert not hasattr(connection, "commit") and not hasattr(connection, "rollback")


@pytest.mark.parametrize("state", ["WA", "VIC"])
def test_unknown_or_duplicate_jurisdiction_rejected_before_sql(context, state):
    value = context.manifest.as_dict()
    value["sources"][0]["jurisdiction_code"] = state
    changed = replace(context, manifest=FrozenManifest(json.dumps(value)))
    with pytest.raises(IntakeError, match="supported projection") as error:
        dispatcher.project(ModuleConnection(Transaction()), changed)
    assert error.value.code == "PROJECT_SOURCE"


def test_context_kind_mismatch_rejected_before_sql(context):
    with pytest.raises(IntakeError) as error:
        dispatcher.project(ModuleConnection(Transaction()), replace(context, dataset_kind="official"))
    assert error.value.code == "PROJECT_KIND"


def test_autocommit_is_rejected(context):
    connection = Transaction()
    connection.autocommit = True
    with pytest.raises(IntakeError) as error:
        dispatcher.project(ModuleConnection(connection), context)
    assert error.value.code == "PROJECT_TRANSACTION"
