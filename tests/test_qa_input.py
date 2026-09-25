"""Native S0 checks and scripted Raw replies; no PostgreSQL server is used."""
from copy import deepcopy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
from uuid import UUID

import pytest

from arsia_ingest.manifest import build_manifest, read_json, s0_definitions
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.qa_input import check_inputs, check_raw, write_evidence, write_results
from test_manifest import ROOT, assemble, build


class RawConnection:
    autocommit = False

    def __init__(self, records):
        self.records = records
        self.calls = []
        self.error = None
        self.closed_cursors = 0

    def cursor(self):
        return RawCursor(self)

    def commit(self):
        pytest.fail("QA must leave commit to the runner")

    def rollback(self):
        pytest.fail("QA must leave rollback to the runner")

    def close(self):
        pytest.fail("QA must leave the connection open")


class RawCursor:
    def __init__(self, connection):
        self.connection = connection
        self.reply = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.connection.closed_cursors += 1

    def execute(self, statement, parameters=None):
        self.connection.calls.append((statement, parameters))
        if self.connection.error:
            raise self.connection.error
        if statement.lstrip().startswith("INSERT"):
            return
        resource, digest, parser, last_id, repeated_id = parameters
        assert last_id == repeated_id
        self.reply = sorted(
            (r for r in self.connection.records if (r[2], r[3], r[4]) == (resource, digest, parser)
             and (last_id is None or UUID(str(r[0])).int > UUID(last_id).int)), key=lambda r: UUID(str(r[0])).int,
        )[:1000]

    def fetchmany(self, size):
        assert size == 1000
        return self.reply


@pytest.fixture
def sample(build):
    manifest = assemble(build).as_dict()
    records = []
    for path in sorted((build[0] / "records").glob("*.jsonl")):
        for line in path.read_text().splitlines():
            record = json.loads(line)
            records.append([str(UUID(int=len(records) + 1)), *[record[k] for k in (
                "source_id", "resource_id", "file_sha256", "parser_version", "row_locator", "payload")]])
    return manifest, build[0].parents[2], RawConnection(records)


def inputs(sample, tmp_path, **kwargs):
    manifest, root, _ = sample
    return check_inputs(manifest, root, evidence_dir=tmp_path / "input-evidence", producer_version="test-qa-v1",
                        supported_mappings=manifest["rules"]["mappings"], **kwargs)


def raw(sample, tmp_path):
    manifest, root, connection = sample
    return check_raw(connection, manifest, root, evidence_dir=tmp_path / "raw-evidence", producer_version="test-qa-v1")


def concrete(report, resource):
    return next(r for r in report.rows if r["object_key"].startswith(f"file:{resource}:"))


def codes(report):
    return {code for r in report.rows for code in r["evidence"]["reason_codes"]}


def test_s0_files_and_all_native_fields_pass_with_explicit_mapping_support(sample, tmp_path):
    report = inputs(sample, tmp_path)
    assert not report.blocked
    assert len(report.rows) == 8
    for row in report.rows[:-1]:
        assert row["result"] == "pass" and row["affected_count"] == 0
        assert row["actual"] == row["expected"]
        assert set(row["evidence"]) == {"reason_codes", "resolution", "references", "producer_version"}
        detail = row["evidence"]["references"][0]["detail"]
        data = Path(detail["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == detail["sha256"]
        assert len(data.splitlines()) == detail["row_count"]
    assert report.rows[-1]["actual"]["metrics"] == {
        "object_count": 7, "pass_count": 7, "limited_count": 0, "block_count": 0, "missing_count": 0,
    }


def test_raw_s0_keeps_node_observations_empty_values_and_all_197_columns(sample, tmp_path):
    report = raw(sample, tmp_path)
    assert not report.blocked and len(report.rows) == 8
    assert sum(r["actual"]["metrics"]["raw_count"] for r in report.rows[:-1]) == 19
    assert concrete(report, "syn_vic_node")["actual"]["metrics"]["raw_count"] == 4
    assert all(r["actual"] == r["expected"] for r in report.rows[:-1])
    assert sample[2].closed_cursors == 7
    for statement, parameters in sample[2].calls:
        assert "FROM raw.record" in statement and "LIMIT 1000" in statement
        assert parameters[:3] in {(f["resource_id"], f["file_sha256"], f["parser_version"]) for f in sample[0]["files"]}


@pytest.mark.parametrize("change", ["value", "type", "missing_field", "extra_field", "null_to_empty", "source"])
def test_raw_detects_same_count_wrong_field_value_type_or_source(sample, tmp_path, change):
    record = next(r for r in sample[2].records if r[2] == "syn_nsw_crash")
    payload = record[-1]
    if change == "value":
        payload["Crash ID"] = "1"
    elif change == "type":
        payload["Crash ID"] = 1
    elif change == "missing_field":
        payload.pop("Crash ID")
    elif change == "extra_field":
        payload["unexpected"] = "x"
    elif change == "null_to_empty":
        key = next(k for k, v in payload.items() if v is None)
        payload[key] = ""
    else:
        record[1] = "syn_another_source"
    report = raw(sample, tmp_path)
    row = concrete(report, "syn_nsw_crash")
    assert row["result"] == "block" and row["affected_count"] == 1
    assert row["actual"]["metrics"]["raw_count"] == 2
    assert row["actual"]["metrics"]["payload_mismatch_count"] == (0 if change == "source" else 1)
    assert ("RAW_IDENTITY_MISMATCH" if change == "source" else "RAW_PAYLOAD_MISMATCH") in codes(report)
    assert report.rows[-1]["affected_count"] == 1


def test_same_total_missing_and_extra_locator_cannot_pass(sample, tmp_path):
    record = next(r for r in sample[2].records if r[2] == "syn_qld_crash")
    record[-2] = "csv:999"
    report = raw(sample, tmp_path)
    row = concrete(report, "syn_qld_crash")
    assert row["actual"]["metrics"]["raw_count"] == row["expected"]["metrics"]["raw_count"] == 2
    assert row["actual"]["evaluated_count"] == 1
    assert row["affected_count"] == 2
    assert {"RAW_MISSING_LOCATOR", "RAW_EXTRA_LOCATOR"} <= codes(report)


def test_duplicate_raw_locator_is_distinct_from_duplicate_native_node_keys(sample, tmp_path):
    records = [r for r in sample[2].records if r[2] == "syn_vic_node"]
    records[1][-2] = records[0][-2]
    report = raw(sample, tmp_path)
    row = concrete(report, "syn_vic_node")
    assert row["actual"]["metrics"]["distinct_locator_count"] == 3
    assert {"RAW_DUPLICATE_LOCATOR", "RAW_MISSING_LOCATOR"} <= codes(report)


@pytest.mark.parametrize("broken", ["missing_archive", "changed_hash", "parser"])
def test_unavailable_native_check_never_reports_pass(sample, tmp_path, broken):
    file = sample[0]["files"][0]
    archive = sample[1] / "synthetic/archive/sha256" / file["file_sha256"][:2] / file["file_sha256"]
    if broken == "missing_archive":
        archive.unlink()
    elif broken == "changed_hash":
        archive.write_bytes(b"changed")
    else:
        file["parser_version"] = "unavailable-parser-v2"
        next(c for c in sample[0]["rules"]["contracts"] if c["id"] == file["resource_id"])["content"]["input"]["parser_version"] = file["parser_version"]
    report = inputs(sample, tmp_path)
    row = concrete(report, file["resource_id"])
    assert row["result"] == "block" and row["actual"]["evaluated_count"] == 0
    assert row["actual"]["metrics"]["header_match"] is None
    report = raw(sample, tmp_path)
    assert all(v is None for v in concrete(report, file["resource_id"])["actual"]["metrics"].values())


def test_database_error_leaves_raw_metrics_unmeasured(sample, tmp_path):
    sample[2].error = RuntimeError("test unavailable connection")
    report = raw(sample, tmp_path)
    assert report.blocked and len(report.rows) == 8
    for row in report.rows[:-1]:
        assert row["actual"]["evaluated_count"] == 0
        assert all(value is None for value in row["actual"]["metrics"].values())
        assert "RAW_CHECK_UNAVAILABLE" in row["evidence"]["reason_codes"]


def test_missing_mapping_support_and_changed_operations_block(sample, tmp_path):
    manifest, root, _ = sample
    report = check_inputs(manifest, root, evidence_dir=tmp_path / "no-support", producer_version="test-v1")
    assert report.blocked and "MAPPING_UNSUPPORTED" in codes(report)
    supported = deepcopy(manifest["rules"]["mappings"])
    manifest["rules"]["mappings"][0]["content"]["unknown_operation"] = "invented"
    report = check_inputs(manifest, root, evidence_dir=tmp_path / "changed-operation", producer_version="test-v1", supported_mappings=supported)
    assert report.blocked and "MAPPING_UNSUPPORTED" in codes(report)


def _official(sample, *, draft):
    manifest = json.loads(json.dumps(sample[0]).replace("syn_", "official_"))
    manifest["dataset_kind"] = "official"
    for item in manifest["provenance"]["files"]:
        item["archive_relpath"] = item["archive_relpath"].replace("synthetic/", "official/")
        item["download_url"] = "https://example.test/official.csv"
    for contract in manifest["rules"]["contracts"]:
        contract["status"] = "draft" if draft else "confirmed"
        contract["content"]["confirmation"] = {
            "status": contract["status"], "owner": "fixture", "reviewed_by": "fixture",
            "licence": "fixture", "checked_at": "2026-09-19", "references": ["fixture only"], "unresolved": [],
        }
    shutil.copytree(sample[1] / "synthetic/archive", sample[1] / "official/archive")
    return manifest


@pytest.mark.parametrize("draft", [True, False])
def test_renaming_synthetic_to_official_does_not_approve_source(sample, tmp_path, draft):
    manifest = _official(sample, draft=draft)
    report = check_inputs(manifest, sample[1], evidence_dir=tmp_path / "official", producer_version="test-v1", supported_mappings=manifest["rules"]["mappings"])
    assert report.blocked
    assert all(r["actual"]["metrics"]["bundle_confirmed"] is False for r in report.rows[:-1])
    assert "CONTRACT_UNCONFIRMED" in codes(report)


def _variant(build, tmp_path, name):
    spec = importlib.util.spec_from_file_location("s0_qa_generator", ROOT / "tools/create_s0_inputs.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    path = tmp_path / name
    config = generator.create_s0(path, name)
    prepared = prepare(config, build[0].parents[2])
    kwargs = {**build[1], **s0_definitions(path / "contract.json")}
    return build_manifest(prepared["run_dir"], **kwargs).as_dict()


@pytest.mark.parametrize("name,blocked", [("revised_n1", False), ("delete_q2", False), ("delete_q2_unexplained", True)])
def test_generated_snapshot_changes_are_checked_against_previous_archive(build, sample, tmp_path, name, blocked):
    current = _variant(build, tmp_path, name)
    report = check_inputs(current, sample[1], previous_manifest=sample[0], evidence_dir=tmp_path / "changes", producer_version="test-v1", supported_mappings=current["rules"]["mappings"])
    assert report.blocked is blocked
    if blocked:
        assert "SNAPSHOT_DELETION_UNEXPLAINED" in codes(report)


def test_same_count_native_key_replacement_is_an_unexplained_deletion(sample, tmp_path):
    before = deepcopy(sample[0])
    file = next(f for f in sample[0]["files"] if f["resource_id"] == "syn_qld_crash")
    old_path = sample[1] / "synthetic/archive/sha256" / file["file_sha256"][:2] / file["file_sha256"]
    data = old_path.read_bytes().replace(b"0002", b"0003")
    digest = hashlib.sha256(data).hexdigest()
    new_path = sample[1] / "synthetic/archive/sha256" / digest[:2] / digest
    new_path.parent.mkdir(exist_ok=True)
    new_path.write_bytes(data)
    file["file_sha256"] = digest
    next(c for c in sample[0]["rules"]["contracts"] if c["id"] == file["resource_id"])["content"]["input"] = deepcopy(file)
    provenance = next(p for p in sample[0]["provenance"]["files"] if p["resource_id"] == file["resource_id"])
    provenance.update(file_sha256=digest, archive_relpath=f"synthetic/archive/sha256/{digest[:2]}/{digest}")
    report = inputs(sample, tmp_path, previous_manifest=before)
    assert report.blocked and "SNAPSHOT_DELETION_UNEXPLAINED" in codes(report)


def test_missing_previous_archive_blocks_history_check(build, sample, tmp_path):
    current = _variant(build, tmp_path, "revised_n1")
    previous = next(f for f in sample[0]["files"] if f["resource_id"] == "syn_nsw_crash")
    (sample[1] / "synthetic/archive/sha256" / previous["file_sha256"][:2] / previous["file_sha256"]).unlink()
    report = check_inputs(current, sample[1], previous_manifest=sample[0], evidence_dir=tmp_path / "history-missing", producer_version="test-v1", supported_mappings=current["rules"]["mappings"])
    assert concrete(report, "syn_nsw_crash")["result"] == "block"


def test_coverage_shrinkage_requires_its_own_explanation(sample, tmp_path):
    before = deepcopy(sample[0])
    sample[0]["rules"]["contracts"][0]["content"]["identity"]["coverage"]["year_from"] = 2021
    report = inputs(sample, tmp_path, previous_manifest=before)
    assert report.blocked and "COVERAGE_CHANGE_UNEXPLAINED" in codes(report)


@pytest.mark.parametrize("case", [
    "boolean", "stale_range", "stale_pair", "wrong_before", "wrong_after",
    "missing_before", "extra_member", "boolean_in_pair", "valid", "valid_replacement",
])
def test_coverage_change_statement_matches_both_snapshots(sample, tmp_path, case):
    previous = deepcopy(sample[0])
    contract = sample[0]["rules"]["contracts"][0]
    old = deepcopy(contract["content"]["identity"]["coverage"])
    contract["content"]["identity"]["coverage"]["year_to"] = 2023
    new = deepcopy(contract["content"]["identity"]["coverage"])
    declared = {"before": deepcopy(old), "after": deepcopy(new)}
    if case == "boolean":
        declared = True
    elif case == "stale_range":
        declared = deepcopy(old)
    elif case == "stale_pair":
        declared["after"] = deepcopy(old)
    elif case == "wrong_before":
        declared["before"]["year_from"] = 2019
    elif case == "wrong_after":
        declared["after"]["months"] = list(range(1, 12))
    elif case == "missing_before":
        del declared["before"]
    elif case == "extra_member":
        declared["approved"] = True
    elif case == "boolean_in_pair":
        declared["after"]["months"][0] = True
    contract["content"]["snapshot"]["change"] = {
        "source_id": contract["content"]["input"]["source_id"],
        "previous_release_label": contract["content"]["identity"]["release_label"],
        "kind": "replacement" if case == "valid_replacement" else "coverage_reduction",
        "description": "The new snapshot covers 2020–2023; 2024 is no longer covered.",
        "coverage": declared,
    }
    report = inputs(sample, tmp_path, previous_manifest=previous)
    row = concrete(report, contract["id"])
    valid = case in {"valid", "valid_replacement"}
    assert report.blocked == (not valid)
    assert row["result"] == report.rows[-1]["result"] == ("pass" if valid else "block")
    if not valid:
        assert row["evidence"]["reason_codes"] == ["COVERAGE_CHANGE_UNEXPLAINED"]
        reference = row["evidence"]["references"][0]["detail"]
        data = Path(reference["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == reference["sha256"]
        details = [json.loads(line) for line in data.splitlines()]
        failure = next(item for item in details if item.get("reason_code") == "COVERAGE_CHANGE_UNEXPLAINED")
        assert failure["expected"] == old and failure["actual"] == new
        assert failure["declared"] == declared


@pytest.mark.parametrize("case", [
    "month_shrink", "bool_month", "invalid_month", "duplicate_month", "nested_month",
    "extra_dimension", "basis_change", "year_expansion", "month_expansion", "month_reorder",
])
def test_coverage_expansion_only_accepts_valid_unchanged_dimensions(sample, tmp_path, case):
    previous = deepcopy(sample[0])
    old = previous["rules"]["contracts"][0]["content"]["identity"]["coverage"]
    contract = sample[0]["rules"]["contracts"][0]
    new = contract["content"]["identity"]["coverage"]
    if case == "month_shrink":
        new["months"].remove(12)
    elif case == "bool_month":
        new["months"][0] = True
    elif case == "invalid_month":
        new["months"].append(13)
    elif case == "duplicate_month":
        new["months"].append(1)
    elif case == "nested_month":
        new["months"].append([1])
    elif case == "extra_dimension":
        old["regions"] = ["north", "south"]
        new["regions"] = ["north"]
    elif case == "basis_change":
        new["basis"] = "Only part of the former area is covered."
    elif case == "year_expansion":
        old["year_to"] = 2023
    elif case == "month_expansion":
        old["months"].remove(12)
    else:
        new["months"].reverse()
    report = inputs(sample, tmp_path, previous_manifest=previous)
    expands = case in {"year_expansion", "month_expansion", "month_reorder"}
    assert report.blocked == (not expands)
    if not expands:
        assert "COVERAGE_CHANGE_UNEXPLAINED" in concrete(report, contract["id"])["evidence"]["reason_codes"]


def test_report_rows_insert_without_updates_or_transaction_ownership(sample, tmp_path):
    report = inputs(sample, tmp_path)
    connection = RawConnection([])
    write_results(connection, UUID(int=100), report)
    assert len(connection.calls) == 8
    for (statement, values), row in zip(connection.calls, report.rows):
        assert statement.lstrip().startswith("INSERT INTO qa.check_result")
        assert "ON CONFLICT" not in statement and "UPDATE" not in statement
        assert len(values) == 10 and values[0] == str(UUID(int=100))
        assert json.loads(values[5]) == row["actual"]
        assert json.loads(values[7]) == row["evidence"]


def test_evidence_files_are_create_only_and_report_keeps_prior_bytes(sample, tmp_path):
    report = inputs(sample, tmp_path)
    path = Path(report.rows[0]["evidence"]["references"][0]["detail"]["path"])
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        inputs(sample, tmp_path)
    assert path.read_bytes() == before
    target = tmp_path / "run.json"
    reference = write_evidence(target, report.as_dict())
    assert reference["row_count"] == 1
    assert hashlib.sha256(target.read_bytes()).hexdigest() == reference["sha256"]
    with pytest.raises(FileExistsError):
        write_evidence(target, {"changed": True})


def test_qa_rejects_autocommit_before_query(sample, tmp_path):
    sample[2].autocommit = True
    with pytest.raises(IntakeError, match="autocommit"):
        raw(sample, tmp_path)
    assert sample[2].calls == []


def _replace_archive(sample, resource, data, count):
    file = next(f for f in sample[0]["files"] if f["resource_id"] == resource)
    digest = hashlib.sha256(data).hexdigest()
    path = sample[1] / "synthetic/archive/sha256" / digest[:2] / digest
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    file.update(file_sha256=digest, raw_count=count)
    next(c for c in sample[0]["rules"]["contracts"] if c["id"] == resource)["content"]["input"] = deepcopy(file)
    provenance = next(p for p in sample[0]["provenance"]["files"] if p["resource_id"] == resource)
    provenance.update(file_sha256=digest, archive_relpath=f"synthetic/archive/sha256/{digest[:2]}/{digest}")
    return file


def test_changed_ordered_header_blocks_even_with_matching_file_hash(sample, tmp_path):
    file = next(f for f in sample[0]["files"] if f["resource_id"] == "syn_qld_crash")
    path = sample[1] / "synthetic/archive/sha256" / file["file_sha256"][:2] / file["file_sha256"]
    _replace_archive(sample, file["resource_id"], path.read_bytes().replace(b"Crash_Ref_Number", b"Renamed_Ref_Number"), 2)
    row = concrete(inputs(sample, tmp_path), file["resource_id"])
    assert row["result"] == "block"
    assert row["actual"]["metrics"]["hash_match"] is True
    assert row["actual"]["metrics"]["header_match"] is False
    assert row["actual"]["evaluated_count"] == 0


@pytest.mark.parametrize("count", [0, 1001])
def test_raw_empty_file_and_uuid_pagination(sample, tmp_path, count):
    rid = "syn_qld_crash"
    selected = next(f for f in sample[0]["files"] if f["resource_id"] == rid)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=selected["header"])
    writer.writeheader()
    payloads = []
    for i in range(count):
        payload = dict.fromkeys(selected["header"], "")
        payload["Crash_Ref_Number"] = f"{i:06d}"
        payloads.append(payload)
        writer.writerow(payload)
    file = _replace_archive(sample, rid, output.getvalue().encode(), count)
    sample[2].records = [r for r in sample[2].records if r[2] != rid]
    sample[2].records.extend([str(UUID(int=2000 + i)), file["source_id"], rid, file["file_sha256"], file["parser_version"], f"csv:{i + 1}", payload]
                             for i, payload in enumerate(payloads))
    report = raw(sample, tmp_path)
    assert not report.blocked
    row = concrete(report, rid)
    assert row["actual"] == row["expected"]
    assert row["actual"]["metrics"]["raw_count"] == count
    calls = [params for sql, params in sample[2].calls if params[0] == rid]
    assert len(calls) == (1 if count == 0 else 2)
    if count:
        assert calls[1][-1] == str(UUID(int=2999))


def test_current_raw_archive_symlink_is_rejected(sample, tmp_path):
    file = sample[0]["files"][0]
    path = sample[1] / "synthetic/archive/sha256" / file["file_sha256"][:2] / file["file_sha256"]
    elsewhere = tmp_path / "elsewhere"
    path.rename(elsewhere)
    path.symlink_to(elsewhere)
    report = inputs(sample, tmp_path)
    assert "QA_ARCHIVE" in codes(report)
    report = raw(sample, tmp_path)
    assert "QA_ARCHIVE" in codes(report)
