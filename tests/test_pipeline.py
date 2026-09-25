"""Tests for preparation output, archive reuse and failed runs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from openpyxl import Workbook
import pytest

import arsia_ingest.pipeline as pipeline
from arsia_ingest.models import IntakeError


ROW_KEYS = {"source_id", "resource_id", "file_sha256", "parser_version", "row_locator", "payload"}
FILE_KEYS = {
    "source_id", "resource_id", "resource_role", "entity_kind", "file_sha256",
    "parser_version", "locator_version", "format", "encoding", "sheet",
    "header_row", "header", "raw_count",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def resource(path: Path, name="syn_crash", kind="synthetic", header=None, **overrides):
    spec = {
        "source_id": "syn_test" if kind == "synthetic" else "official_test",
        "resource_id": name, "resource_role": "crash", "entity_kind": "crash",
        "path": str(path), "format": "csv", "encoding": "utf-8", "sheet": None,
        "header_row": 1, "header": header or ["ID", "Value"],
    }
    spec.update(overrides)
    return spec


def config(tmp_path: Path, specs: list[dict], kind="synthetic", filename="inputs.json") -> Path:
    path = tmp_path / filename
    path.write_text(json.dumps({
        "config_version": "intake-v1", "dataset_kind": kind, "resources": specs,
    }), encoding="utf-8")
    return path


def archive_path(output: Path, data: bytes, kind="synthetic") -> Path:
    digest = sha(data)
    return output / kind / "archive" / "sha256" / digest[:2] / digest


def record_path(summary: dict, resource_id="syn_crash") -> Path:
    item = next(item for item in summary["files"] if item["resource_id"] == resource_id)
    return Path(summary["run_dir"]) / item["records_path"]


def assert_failed_without_exports(summary: dict) -> Path:
    run_dir = Path(summary["run_dir"])
    assert summary["status"] == "failed"
    assert summary["files"] == []
    assert summary["raw_count"] == 0
    assert summary["errors"]
    assert summary["errors"][0]["run_id"] == summary["run_id"]
    assert not (run_dir / "records").exists()
    assert not (run_dir / "files.json").exists()
    assert not (run_dir / "provenance.json").exists()
    assert read_json(run_dir / "run.json") == summary
    events = read_jsonl(run_dir / "events.jsonl")
    assert all(event["run_id"] == summary["run_id"] for event in events)
    assert events[-1]["event"] == "run_failed"
    return run_dir


def test_complete_csv_run_preserves_native_data_and_exact_l1_contract(tmp_path):
    data = b'\xef\xbb\xbfID,Year,Value\r\n0001,1999,Unknown\r\n0001,1999,Unknown\r\n\r\n0002,2026,"line 1\nline 2"\r\n,,\r\n'
    source = tmp_path / "crash.csv"
    source.write_bytes(data)
    spec = resource(source, header=["ID", "Year", "Value"], expected_sha256=sha(data))
    output = tmp_path / "output"
    summary = pipeline.prepare(config(tmp_path, [spec]), output)

    assert summary["status"] == "prepared"
    assert summary["scope"] == "native_preparation_only"
    assert summary["raw_count"] == 4
    assert summary["errors"] == []
    assert "batch_id" not in summary
    assert "input_fingerprint" not in summary
    run_dir = Path(summary["run_dir"])
    assert read_json(run_dir / "run.json") == summary
    rows = read_jsonl(record_path(summary))
    assert all(set(row) == ROW_KEYS for row in rows)
    assert [row["row_locator"] for row in rows] == ["csv:1", "csv:2", "csv:4", "csv:5"]
    assert rows[0]["payload"] == rows[1]["payload"] == {"ID": "0001", "Year": "1999", "Value": "Unknown"}
    assert rows[2]["payload"] == {"ID": "0002", "Year": "2026", "Value": "line 1\nline 2"}
    assert rows[3]["payload"] == {"ID": "", "Year": "", "Value": ""}
    assert all(row["file_sha256"] == sha(data) and row["source_id"] == "syn_test" for row in rows)

    files = read_json(run_dir / "files.json")
    assert set(files) == {"files"}
    assert len(files["files"]) == 1
    metadata = files["files"][0]
    assert set(metadata) == FILE_KEYS
    assert metadata == {
        "source_id": "syn_test", "resource_id": "syn_crash", "resource_role": "crash",
        "entity_kind": "crash", "file_sha256": sha(data), "parser_version": "csv-native-v1",
        "locator_version": "csv-logical-v1", "format": "csv", "encoding": "utf-8",
        "sheet": None, "header_row": 1, "header": ["ID", "Year", "Value"], "raw_count": 4,
    }
    item = summary["files"][0]
    assert item["blank_records_skipped"] == 1
    assert item["records_seen"] == 5
    assert item["records_sha256"] == sha(record_path(summary).read_bytes())
    provenance = read_json(run_dir / "provenance.json")
    assert provenance["run_id"] == summary["run_id"]
    archived = output / provenance["files"][0]["archive_relpath"]
    assert archived == archive_path(output, data)
    assert archived.read_bytes() == source.read_bytes() == data
    events = read_jsonl(run_dir / "events.jsonl")
    assert all(event["run_id"] == summary["run_id"] for event in events)
    assert events[-1]["event"] == "run_prepared"
    assert events[-1]["raw_count"] == 4


def test_mixed_csv_and_xlsx_share_l1_structure_and_use_archived_bytes(tmp_path):
    csv_file = tmp_path / "crash.csv"
    csv_file.write_bytes(b"ID,Value\n0001,\n")
    xlsx_file = tmp_path / "units.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Native Data"
    sheet.append(["ID", "Value"])
    sheet.append(["0001", None])
    sheet.append(["0002", 0.000001])
    workbook.save(xlsx_file)
    workbook.close()
    specs = [resource(csv_file), resource(
        xlsx_file, name="syn_units", resource_role="vehicle", entity_kind="unit",
        format="xlsx", encoding=None, sheet="Native Data",
    )]
    summary = pipeline.prepare(config(tmp_path, specs), tmp_path / "output")
    assert summary["status"] == "prepared", summary["errors"]
    csv_rows = read_jsonl(record_path(summary))
    xlsx_rows = read_jsonl(record_path(summary, "syn_units"))
    assert set(csv_rows[0]) == set(xlsx_rows[0]) == ROW_KEYS
    assert csv_rows[0]["payload"]["Value"] == ""
    assert xlsx_rows[0]["payload"] == {"ID": "0001", "Value": None}
    assert xlsx_rows[1]["payload"]["Value"] == "0.000001"
    assert json.loads(xlsx_rows[0]["row_locator"]) == ["Native Data", 2]
    assert summary["raw_count"] == 3
    assert archive_path(tmp_path / "output", xlsx_file.read_bytes()).is_file()


def test_repeat_and_input_relocation_produce_identical_records_and_file_metadata(tmp_path):
    data = b"ID,Value\n0001,Unknown\n"
    source = tmp_path / "input.csv"
    source.write_bytes(data)
    output = tmp_path / "output"
    first_config = config(tmp_path, [resource(source, expected_sha256=sha(data))])
    first = pipeline.prepare(first_config, output)
    second = pipeline.prepare(first_config, output)
    moved = tmp_path / "elsewhere"
    moved.mkdir()
    relocated = moved / "renamed.csv"
    shutil.copyfile(source, relocated)
    third_config = config(tmp_path, [resource(relocated, expected_sha256=sha(data))], filename="relocated.json")
    third = pipeline.prepare(third_config, output)
    assert {first["status"], second["status"], third["status"]} == {"prepared"}
    assert len({first["run_id"], second["run_id"], third["run_id"]}) == 3
    assert record_path(first).read_bytes() == record_path(second).read_bytes() == record_path(third).read_bytes()
    metadata = [read_json(Path(summary["run_dir"]) / "files.json") for summary in (first, second, third)]
    assert metadata[0] == metadata[1] == metadata[2]
    originals = list((output / "synthetic" / "archive" / "sha256").glob("*/*"))
    assert originals == [archive_path(output, data)]
    assert all("input_fingerprint" not in summary and summary["status"] != "no_change" for summary in (first, second, third))


@pytest.mark.parametrize("problem,code", [
    ("missing", "IO_ERROR"), ("header", "HEADER_MISMATCH"), ("hash", "FILE_HASH_MISMATCH"),
])
def test_input_failures_leave_diagnostics_and_no_consumable_exports(tmp_path, problem, code):
    source = tmp_path / "input.csv"
    data = b"ID,Wrong\n0001,x\n" if problem == "header" else b"ID,Value\n0001,x\n"
    if problem != "missing":
        source.write_bytes(data)
    spec = resource(source)
    if problem == "hash":
        spec["expected_sha256"] = "0" * 64
    output = tmp_path / "output"
    summary = pipeline.prepare(config(tmp_path, [spec]), output)
    assert_failed_without_exports(summary)
    assert summary["errors"][0]["code"] == code
    assert summary["errors"][0]["resource_id"] == "syn_crash"
    if problem != "missing":
        assert archive_path(output, data).read_bytes() == data


def test_late_second_file_error_discards_all_current_exports_and_preserves_previous_run(tmp_path):
    first_file = tmp_path / "valid.csv"
    first_file.write_bytes(b"ID,Value\n0001,ok\n")
    output = tmp_path / "output"
    successful = pipeline.prepare(config(tmp_path, [resource(first_file)]), output)
    previous_bytes = record_path(successful).read_bytes()
    second_file = tmp_path / "invalid.csv"
    second_file.write_bytes(b"ID,Value\n0002,ok\n0003,too,many\n")
    specs = [resource(first_file), resource(second_file, name="syn_other")]
    failed = pipeline.prepare(config(tmp_path, specs, filename="two.json"), output)
    run_dir = assert_failed_without_exports(failed)
    error = failed["errors"][0]
    assert error["code"] == "ROW_WIDTH_MISMATCH"
    assert error["resource_id"] == "syn_other"
    assert error["row_locator"] == "csv:2"
    assert error["partial_stats"]["raw_count"] == 1
    assert record_path(successful).read_bytes() == previous_bytes
    assert read_json(Path(successful["run_dir"]) / "run.json")["status"] == "prepared"
    assert archive_path(output, first_file.read_bytes()).is_file()
    assert archive_path(output, second_file.read_bytes()).is_file()
    assert any(event["event"] == "file_prepared" for event in read_jsonl(run_dir / "events.jsonl"))


def test_tampered_existing_archive_is_detected_and_never_overwritten(tmp_path):
    data = b"ID,Value\n0001,x\n"
    source = tmp_path / "input.csv"
    source.write_bytes(data)
    output = tmp_path / "output"
    config_path = config(tmp_path, [resource(source)])
    first = pipeline.prepare(config_path, output)
    archived = archive_path(output, data)
    archived.write_bytes(b"tampered archive")
    failed = pipeline.prepare(config_path, output)
    assert_failed_without_exports(failed)
    assert failed["errors"][0]["code"] == "ARCHIVE_INTEGRITY"
    assert archived.read_bytes() == b"tampered archive"
    assert source.read_bytes() == data
    assert record_path(first).is_file()


def test_symlink_at_archive_address_is_rejected_without_modifying_target(tmp_path):
    data = b"ID,Value\n0001,x\n"
    source = tmp_path / "input.csv"
    source.write_bytes(data)
    output = tmp_path / "output"
    destination = archive_path(output, data)
    destination.parent.mkdir(parents=True)
    destination.symlink_to(source)
    failed = pipeline.prepare(config(tmp_path, [resource(source)]), output)
    assert_failed_without_exports(failed)
    assert failed["errors"][0]["code"] == "ARCHIVE_INTEGRITY"
    assert destination.is_symlink()
    assert source.read_bytes() == data


def test_source_changes_after_archive_do_not_change_frozen_parse_input(tmp_path, monkeypatch):
    data = b"ID,Value\n0001,original\n"
    source = tmp_path / "input.csv"
    source.write_bytes(data)
    original_reader = pipeline.iter_native_rows

    def changed_source_reader(path, spec, stats):
        source.write_bytes(b"ID,Value\n0002,replaced\n")
        yield from original_reader(path, spec, stats)

    monkeypatch.setattr(pipeline, "iter_native_rows", changed_source_reader)
    summary = pipeline.prepare(config(tmp_path, [resource(source, expected_sha256=sha(data))]), tmp_path / "output")
    assert summary["status"] == "prepared"
    assert read_jsonl(record_path(summary))[0]["payload"] == {"ID": "0001", "Value": "original"}
    assert archive_path(tmp_path / "output", data).read_bytes() == data
    assert source.read_bytes() != data


def test_archive_changes_during_parse_block_publication(tmp_path, monkeypatch):
    data = b"ID,Value\n0001,original\n"
    source = tmp_path / "input.csv"
    source.write_bytes(data)
    original_reader = pipeline.iter_native_rows

    def corrupted_archive_reader(path, spec, stats):
        yield from original_reader(path, spec, stats)
        path.write_bytes(b"corrupted after reading")

    monkeypatch.setattr(pipeline, "iter_native_rows", corrupted_archive_reader)
    summary = pipeline.prepare(config(tmp_path, [resource(source)]), tmp_path / "output")
    assert_failed_without_exports(summary)
    assert summary["errors"][0]["code"] == "ARCHIVE_INTEGRITY"


def test_modes_have_distinct_record_ids_and_archive_run_directories(tmp_path):
    data = b"ID,Value\n0001,x\n"
    source = tmp_path / "input.csv"
    source.write_bytes(data)
    output = tmp_path / "output"
    synthetic = pipeline.prepare(config(tmp_path, [resource(source)]), output)
    official = pipeline.prepare(config(
        tmp_path, [resource(source, name="official_crash", kind="official")],
        kind="official", filename="official.json",
    ), output)
    assert synthetic["status"] == official["status"] == "prepared"
    syn_row = read_jsonl(record_path(synthetic))[0]
    official_row = read_jsonl(record_path(official, "official_crash"))[0]
    assert syn_row["source_id"] != official_row["source_id"]
    assert syn_row["resource_id"] != official_row["resource_id"]
    assert Path(synthetic["run_dir"]).parent.parent == output / "synthetic"
    assert Path(official["run_dir"]).parent.parent == output / "official"
    assert archive_path(output, data, "synthetic").read_bytes() == data
    assert archive_path(output, data, "official").read_bytes() == data


def test_lfs_pointer_is_archived_but_not_mistaken_for_downloaded_csv(tmp_path):
    data = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"a" * 64 + b"\nsize 42\n"
    source = tmp_path / "input.csv"
    source.write_bytes(data)
    output = tmp_path / "output"
    summary = pipeline.prepare(config(tmp_path, [resource(source)]), output)
    assert_failed_without_exports(summary)
    assert summary["errors"][0]["code"] == "LFS_POINTER"
    assert archive_path(output, data).read_bytes() == data


def test_invalid_config_fails_before_creating_any_output(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"unexpected":true}', encoding="utf-8")
    output = tmp_path / "output"
    with pytest.raises(IntakeError) as error:
        pipeline.prepare(path, output)
    assert error.value.code == "CONFIG_FIELDS"
    assert not output.exists()


def invoke_cli(path: Path, output: Path):
    environment = os.environ.copy()
    source_root = Path(__file__).resolve().parents[1] / "src"
    environment["PYTHONPATH"] = str(source_root)
    return subprocess.run(
        [sys.executable, "-m", "arsia_ingest", "--config", str(path), "--output", str(output)],
        cwd=path.parent, env=environment, capture_output=True, text=True, timeout=30,
    )


def test_cli_exit_codes_distinguish_prepared_input_failure_and_bad_config(tmp_path):
    source = tmp_path / "input.csv"
    source.write_bytes(b"ID,Value\n0001,x\n")
    good_config = config(tmp_path, [resource(source)])
    prepared = invoke_cli(good_config, tmp_path / "good")
    assert prepared.returncode == 0, prepared.stderr
    assert json.loads(prepared.stdout)["status"] == "prepared"
    assert prepared.stderr == ""

    source.unlink()
    failed = invoke_cli(good_config, tmp_path / "failed")
    assert failed.returncode == 1
    assert json.loads(failed.stdout)["status"] == "failed"
    assert failed.stderr == ""

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    rejected = invoke_cli(invalid, tmp_path / "rejected")
    assert rejected.returncode == 2
    assert json.loads(rejected.stderr)["code"] == "CONFIG_FIELDS"
    assert rejected.stdout == ""
    assert not (tmp_path / "rejected").exists()


def test_cleanup_failure_still_revokes_manifest_and_persists_failed_receipt(tmp_path, monkeypatch):
    source = tmp_path / "input.csv"
    source.write_bytes(b"ID,Value\n0001,x\n")
    original_write_json = pipeline._write_json

    def fail_after_provenance_write(path, value):
        original_write_json(path, value)
        if path.name == "provenance.json":
            raise PermissionError("Injected filesystem failure after metadata publication")

    def deny_records_cleanup(path, *args, **kwargs):
        raise PermissionError("Injected inability to remove records directory")

    monkeypatch.setattr(pipeline, "_write_json", fail_after_provenance_write)
    monkeypatch.setattr(pipeline.shutil, "rmtree", deny_records_cleanup)
    summary = pipeline.prepare(config(tmp_path, [resource(source)]), tmp_path / "output")
    run_dir = Path(summary["run_dir"])
    assert summary["status"] == "failed"
    assert summary["files"] == []
    assert summary["raw_count"] == 0
    assert {error["code"] for error in summary["errors"]} >= {"IO_ERROR", "CLEANUP_ERROR"}
    # Even if records cannot be deleted, removable metadata must be cleared
    # and the receipt must mark the run as failed.
    assert (run_dir / "records").exists()
    assert not (run_dir / "files.json").exists()
    assert not (run_dir / "provenance.json").exists()
    assert read_json(run_dir / "run.json") == summary
    assert read_jsonl(run_dir / "events.jsonl")[-1]["event"] == "run_failed"
