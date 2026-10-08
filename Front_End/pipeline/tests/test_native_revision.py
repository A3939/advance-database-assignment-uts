"""Synthetic dispatch tests; they do not claim official new-version admission."""
import copy
from dataclasses import FrozenInstanceError
import hashlib
import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from arsia_pipeline import native, native_revision
from arsia_pipeline.errors import NeedsInput, ValidationFailure
from test_native import file_info, write_csv


def extracted_session(tmp_path, files):
    from arsia_pipeline.agent import AgentSession
    from arsia_pipeline.intake_tools import IntakeTools
    archive_path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive_path,"w") as archive:
        for file in files:
            archive.write(file["path"],file["name"])
    intake = IntakeTools([file_info(archive_path)],tmp_path/"intake",lambda:None)
    intake.inspect_bundle()
    session = object.__new__(AgentSession)
    session.files,session.cancel,session.native_context,session.messages = intake.files,lambda:None,None,[]
    session.sample_gate,session.validated,session.registered = None,None,None
    return session


def test_native_zip_derived_bytes_cannot_be_registered_as_unrelated_source(tmp_path):
    session = extracted_session(tmp_path,complete(tmp_path,"QLD"))
    session.enforce_native_boundary()
    assert session.native_context.source_id == "official_qld"
    assert all(row["file_id"].startswith("zip-") for row in session.native_context.receipt["inputs"])
    assert session.messages and "official_qld" in session.messages[-1]["content"]


def test_incomplete_native_zip_cannot_fall_through_generic(tmp_path):
    session = extracted_session(tmp_path,complete(tmp_path,"NSW")[:1])
    with pytest.raises(native_revision.NativeBoundary,match="original native files|incomplete"):
        session.enforce_native_boundary()


def test_exact_pinned_native_zip_pauses_for_deterministic_upload(tmp_path,monkeypatch):
    files = complete(tmp_path,"QLD")
    session = extracted_session(tmp_path,files)
    upstream,refs = native._references()
    refs = copy.deepcopy(refs)
    next(value for value in refs["native-inputs.json"]["resources"] if value["source_id"] == "official_qld")["expected_sha256"] = files[0]["sha256"]
    monkeypatch.setattr(native,"_references",lambda:(upstream,refs))
    with pytest.raises(native_revision.NativeBoundary,match="exact frozen native bundle") as error:
        session.enforce_native_boundary()
    assert error.value.details["generic_fallback_allowed"] is False


def complete(tmp_path, state):
    resources = [resource for resource in native._references()[1]["native-inputs.json"]["resources"] if resource["source_id"] == "official_"+state.lower()]
    files = []
    for resource in resources:
        if resource["format"] == "xlsx":
            path = tmp_path/(resource["resource_role"]+".xlsx")
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = resource["sheet"]
            sheet.append(resource["header"])
            workbook.save(path)
            files.append(file_info(path))
        else:
            files.append(write_csv(tmp_path/(resource["resource_role"]+".csv"), resource["header"]))
    return files


def contract(context, coverage=None):
    receipt = context.receipt
    coverage = coverage or receipt["baseline_coverage"]
    return {"source": {"source_id": context.source_id, "jurisdiction": [receipt["jurisdiction"]], "grain": "crash",
                       "publisher": receipt["source_identity"]["publisher"], "dataset_url": "https://data."+receipt["jurisdiction"].lower()+".gov.au/dataset/source",
                       "coverage": coverage},
            "resources": [{"role": row["role"], "file_id": row["file_id"], "grain": row["grain"]} for row in receipt["required_resources"]],
            "update": {"mode": "snapshot", **coverage}}


@pytest.mark.parametrize("state,roles", [("NSW", 2), ("QLD", 1), ("VIC", 4)])
def test_complete_changed_native_bundle_yields_immutable_host_context(tmp_path, state, roles):
    files = complete(tmp_path, state)
    context = native_revision.detect_revision(files)
    assert context.source_id == "official_"+state.lower()
    assert len(context.receipt["required_resources"]) == roles
    assert context.receipt["exceptions_inherited"] is False
    assert len(context.receipt["changed_resources"]) == roles
    assert all("path" not in value for value in context.public()["inputs"])
    with pytest.raises(FrozenInstanceError):
        context.receipt_json = "{}"
    receipt = context.receipt
    receipt["source_id"] = "forged"
    assert context.source_id != "forged"
    assert native_revision.validate_revision_context(context, files)["source_id"] == context.source_id


def test_missing_vic_role_and_changed_header_are_native_boundary(tmp_path):
    files = complete(tmp_path, "VIC")
    with pytest.raises(native_revision.NativeBoundary, match="incomplete"):
        native_revision.detect_revision(files[:-1])
    header = native._references()[1]["native-inputs.json"]["resources"][-1]["header"]
    qld = next(v for v in native._references()[1]["native-inputs.json"]["resources"] if v["source_id"] == "official_qld")
    changed = write_csv(tmp_path/"changed.csv", qld["header"]+["NEW_COLUMN"])
    with pytest.raises(native_revision.NativeBoundary, match="unreviewed"):
        native_revision.detect_revision([changed])


def test_unknown_data_does_not_gain_reserved_identity(tmp_path):
    value = write_csv(tmp_path/"unknown.csv", ["event_id","year","severity"])
    assert native_revision.detect_revision([value]) is None
    assert native_revision.classify_native_route([value]).kind == "unknown"
    with pytest.raises(ValidationFailure, match="host-created"):
        native_revision.validate_revision_context({"source_id":"official_qld"}, [value])


def test_same_pinned_bytes_stay_on_deterministic_route(tmp_path, monkeypatch):
    files = complete(tmp_path, "QLD")
    upstream, refs = native._references()
    refs = copy.deepcopy(refs)
    entry = next(value for value in refs["native-inputs.json"]["resources"] if value["source_id"] == "official_qld")
    entry["expected_sha256"] = files[0]["sha256"]
    monkeypatch.setattr(native, "_references", lambda: (upstream, refs))
    assert native_revision.detect_revision(files) is None
    assert native_revision.classify_native_route(files).kind == "pinned"


def test_input_mutation_is_failure_not_revision(tmp_path):
    files = complete(tmp_path, "QLD")
    context = native_revision.detect_revision(files)
    with open(files[0]["path"],"ab") as handle:
        handle.write(b"\n")
    with pytest.raises(ValidationFailure, match="changed after receipt"):
        native_revision.validate_revision_context(context, files)


def test_snapshot_requires_existing_coverage_and_proven_source(tmp_path):
    files = complete(tmp_path, "QLD")
    context = native_revision.detect_revision(files)
    value = contract(context)
    assert native_revision.validate_revision_contract(context, value, files)["status"] == "route_verified"
    value["source"]["source_id"] = "official_nsw"
    with pytest.raises(ValidationFailure, match="proven logical source"):
        native_revision.validate_revision_contract(context, value, files)
    value = contract(context, {"from":"2025-01-01","to":"2025-12-31"})
    with pytest.raises(NeedsInput, match="remove published history"):
        native_revision.validate_revision_contract(context, value, files)
    value = contract(context)
    with pytest.raises(NeedsInput, match="remove published history"):
        native_revision.validate_revision_contract(context, value, files, current_coverage={"from":"2019-01-01","to":"2024-12-31"})


def test_partition_and_missing_required_resource_cannot_generic_bypass(tmp_path):
    files = complete(tmp_path, "NSW")
    context = native_revision.detect_revision(files)
    value = contract(context)
    value["update"]["mode"] = "partition"
    with pytest.raises(NeedsInput, match="complete snapshot only"):
        native_revision.validate_revision_contract(context, value, files)
    value = contract(context)
    value["resources"].pop()
    with pytest.raises(NeedsInput, match="each original required table"):
        native_revision.validate_revision_contract(context, value, files)


def test_vic_node_lookup_is_explicit_limitation_not_fake_observations(tmp_path):
    files = complete(tmp_path, "VIC")
    context = native_revision.detect_revision(files)
    with pytest.raises(NeedsInput, match="lookup"):
        native_revision.validate_revision_contract(context, contract(context), files)


def test_revision_context_allows_added_public_evidence_without_changing_original_receipt(tmp_path):
    files = complete(tmp_path,"QLD")
    context = native_revision.detect_revision(files)
    extra = write_csv(tmp_path/"extra.csv",["document_metadata"])
    extra["role"] = "public_evidence"
    assert native_revision.validate_revision_context(context,files+[extra])["source_id"] == "official_qld"


def test_reserved_identity_structure_only_allowed_with_recomputed_native_context(tmp_path):
    from arsia_pipeline.trusted_qa import validate_contract
    files = complete(tmp_path,"QLD")
    context = native_revision.detect_revision(files)
    value = contract(context)
    value["contract_version"] = "canonical-v2"
    value["source"].update(title="Synthetic QLD revision",licence="Synthetic structural test")
    value["resources"][0].update(key=["Crash_Ref_Number"],table={"format":"csv"},mapping={"date":{"year_field":"Crash_Year"}})
    with pytest.raises(ValidationFailure):
        validate_contract(value,files)
    assert "crash" in validate_contract(value,files,native_context=context)
