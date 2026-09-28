"""Adapter tests use scripted replies, not PostgreSQL."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from conftest import REPO
from arsia_c import person_checks as c06
from arsia_ingest.manifest import COMPONENTS, FrozenManifest, build_manifest, s0_definitions
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import ModuleConnection, RunEvidence


@pytest.fixture
def manifest(tmp_path):
    run = prepare(REPO / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert run["status"] == "prepared"
    inventory = {"components": {}, "schema_files": ["sql/schema.sql"]}
    project = tmp_path / "inventory"
    (project / "sql").mkdir(parents=True)
    for name in (*COMPONENTS, "schema"):
        path = f"sql/{name}.sql"
        (project / path).write_text("-- Test inventory only; no platform implementation.\n")
        if name in COMPONENTS:
            inventory["components"][name] = [path]
    definitions = s0_definitions(REPO / "tests/fixtures/s0/contract.json")
    return build_manifest(
        run["run_dir"], **definitions, inventory=inventory, project_root=project,
        qa_contract=json.loads((REPO / "config/qa-team-v1.1.json").read_text(encoding="utf-8")),
        prepared_by="C06 adapter test",
        origins={c["id"]: {"download_url": None, "evidence_ref": "synthetic test fixture"}
                 for c in definitions["contracts"]},
    )


class Connection:
    autocommit = False

    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        if statement != c06.SQL_PATH.read_text(encoding="utf-8"):
            return
        request = json.loads(parameters[0])
        self.rows = []
        for file in request["files"]:
            self.rows.append({**{k: file[k] for k in ("source_id", "resource_id", "file_sha256", "parser_version")},
                              "kind": "file", "role": file["role"],
                              "expected_count": file["raw_count"], "actual_count": file["raw_count"]})
            for n in range(file["raw_count"]):
                self.rows.append({**{k: file[k] for k in ("source_id", "resource_id", "file_sha256", "parser_version")},
                                  "kind": file["role"], "raw_record_id": f"test-{file['role']}-{n}",
                                  "row_locator": f"csv:{n+1}", "issues": [], "in_scope": True,
                                  "vehicle_reference": "matched", "count_state": "compared", "count_delta": 0})
        if self.mutate:
            self.mutate(self.rows)

    def __iter__(self):
        return iter((row,) for row in self.rows)


def person(rows):
    return next(r for r in rows if r["kind"] == "person")


def test_real_frozen_manifest_selects_exact_inputs_without_provenance(manifest):
    connection = Connection()
    before = manifest.as_dict()
    report, = c06.review_manifest(ModuleConnection(connection), manifest)
    assert report["status"] == "pass" and report["evaluated_count"] == 8
    request = json.loads(connection.calls[-1][1][0])
    assert "provenance" not in request
    assert request["analysis"] == before["analysis"]
    for file in request["files"]:
        expected = next(f for f in before["files"] if f["resource_id"] == file["resource_id"])
        assert {k: v for k, v in file.items() if k != "role"} == expected
    assert manifest.as_dict() == before


@pytest.mark.parametrize("mutation", [
    lambda rows: rows.clear(),
    lambda rows: rows.pop(),
    lambda rows: rows.append(deepcopy(next(r for r in rows if r["kind"] == "file"))),
    lambda rows: person(rows).update(file_sha256="f" * 64),
    lambda rows: person(rows).pop("row_locator"),
    lambda rows: next(r for r in rows if r["kind"] == "file").update(file_sha256="f" * 64),
    lambda rows: rows.__setitem__(next(i for i, r in enumerate(rows) if r["kind"] == "person" and r["row_locator"] == "csv:2"), deepcopy(person(rows))),
])
def test_missing_or_unselected_sql_output_is_not_pass(manifest, mutation):
    with pytest.raises(IntakeError, match="C06"):
        c06.review_manifest(Connection(mutation), manifest)


def test_snapshot_count_mismatch_blocks_even_with_other_valid_rows(manifest):
    def mutate(rows):
        rows.remove(person(rows))
        next(r for r in rows if r["kind"] == "file" and r["role"] == "person")["actual_count"] -= 1
    report, = c06.review_manifest(Connection(mutate), manifest)
    assert report["status"] == "block"
    assert report["reason_counts"]["selected_raw_count_mismatch"] == 1


@pytest.mark.parametrize("change", ["mapping", "missing", "blank_values", "parent", "version"])
def test_changed_frozen_definitions_require_supported_rules(manifest, change):
    value = manifest.as_dict()
    contract = next(c for c in value["rules"]["contracts"] if c["id"] == "syn_vic_person")
    mapping = next(m for m in value["rules"]["mappings"] if m["id"] == "syn_vic_person_mapping")
    if change == "mapping":
        mapping["content"]["vehicle_reference"]["empty_vehicle_id"] = "Unknown new rule"
    elif change == "missing":
        contract["content"]["semantics"]["common_rules"]["missing_rule"] = "NA means missing"
    elif change == "blank_values":
        contract["content"]["semantics"]["common_rules"]["blank_values"]["csv"] = "NA"
    elif change == "parent":
        contract["content"]["identity"]["parent"]["fields"] = ["PERSON_ID"]
    else:
        mapping["version"] = "syn-2"
    connection = Connection()
    with pytest.raises(IntakeError):
        c06.review_manifest(connection, FrozenManifest(json.dumps(value)))
    assert not connection.calls


def test_callback_saves_evidence_before_blocking(manifest, tmp_path):
    def mutate(rows):
        person(rows)["issues"] = ["invalid_person_key", "unmatched_nonblank_vehicle_ref"]
    context = SimpleNamespace(manifest=manifest, dataset_kind="synthetic", run_id="test-run",
                              batch_id="test-batch", evidence=RunEvidence(tmp_path / "qa"))
    with pytest.raises(IntakeError) as exc:
        c06.check_person(ModuleConnection(Connection(mutate)), context)
    assert exc.value.code == "C06_BLOCK"
    result = json.loads((tmp_path / "qa/c06-person.json").read_text())
    report, = result["reports"]
    assert report["affected_count"] == 1
    assert report["diagnostics"][0]["row_locator"] == "csv:1"
    with pytest.raises(FileExistsError):
        c06.check_person(Connection(), context)


def test_signed_count_differences_cannot_cancel(manifest):
    def mutate(rows):
        accidents = [r for r in rows if r["kind"] == "accident"]
        for row, delta in zip(accidents, [-1, 1], strict=True):
            row.update(count_delta=delta, issues=["person_count_mismatch"])
    report, = c06.review_manifest(Connection(mutate), manifest)
    assert report["status"] == "block" and report["affected_count"] == 2
    assert report["declared_count_absolute_delta"] == 2


def test_draft_official_output_always_preserves_definition_block(manifest):
    value = manifest.as_dict()
    files = c06._synthetic_selection(value, next(f for f in value["files"] if f["entity_kind"] == "person_raw"))
    for file in files:
        for key in ("source_id", "resource_id"):
            file[key] = file[key].replace("syn_", "official_", 1)
    connection = Connection()
    report = c06.review_official_draft(connection, files, value["analysis"])
    request = json.loads(connection.calls[-1][1][0])
    assert request["blank_vehicle_allowed"] is None and request["count_scope_confirmed"] is False
    assert report["status"] == "block" and report["declared_count_absolute_delta"] is None
    assert report["reason_counts"]["source_definitions_unconfirmed"] == 1


def test_autocommit_connection_rejected(manifest):
    connection = Connection()
    connection.autocommit = True
    with pytest.raises(IntakeError):
        c06.review_manifest(connection, manifest)
    assert not connection.calls


def test_unknown_counts_are_not_reported_as_zero_difference(manifest):
    def mutate(rows):
        for row in rows:
            if row["kind"] == "accident":
                row.update(count_state="missing", count_delta=None)
    report, = c06.review_manifest(Connection(mutate), manifest)
    assert report["person_count_comparisons"] == 0
    assert report["declared_count_absolute_delta"] is None
