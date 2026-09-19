"""Opt-in QA02 checks against A's database; all writes use the rollback fixture.

The manifest inventory contains hashed test files, not deployed platform SQL.
These tests exercise native-to-Raw comparison, not FP1 or publication.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from arsia_ingest.manifest import build_manifest
from arsia_ingest.qa_input import check_raw
from arsia_ingest.raw_load import RawLoader, load_prepared
from test_manifest import build
from test_raw_load_postgres import connection, s0


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Real PostgreSQL QA02 tests require A's migrated database and ARSIA_TEST_DSN",
)


@pytest.fixture
def frozen(build, s0):
    kwargs = deepcopy(build[1])
    suffix = kwargs["sources"][0]["source_id"].removeprefix("syn_")
    namespace = s0["sources"][0]["source_id"].removesuffix(suffix)

    def rename(value):
        if isinstance(value, str) and value.startswith("syn_"):
            return namespace + value.removeprefix("syn_")
        if isinstance(value, dict):
            return {rename(key): rename(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rename(item) for item in value]
        return value

    kwargs = rename(kwargs)
    assert kwargs["sources"] == s0["sources"]
    return build_manifest(s0["run_dir"], **kwargs)


def detail_rows(row):
    reference = row["evidence"]["references"][0]["detail"]
    data = Path(reference["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == reference["sha256"]
    lines = data.splitlines()
    assert len(lines) == reference["row_count"]
    return [json.loads(line) for line in lines]


def test_postgres_qa02_compares_all_s0_rows_and_retains_node_observations(connection, s0, frozen, tmp_path):
    loaded = load_prepared(connection, s0["run_dir"], s0["sources"])
    assert (loaded.raw_count, loaded.inserted_count) == (19, 19)
    report = check_raw(
        connection, frozen.as_dict(), s0["run_dir"].parents[2],
        evidence_dir=tmp_path / "qa-lossless", producer_version="b11-postgres-test-v1",
    )
    files = frozen.as_dict()["files"]
    by_key = {row["object_key"]: row for row in report.rows}
    expected_keys = {
        f'file:{file["resource_id"]}:{file["file_sha256"]}:{file["parser_version"]}'
        for file in files
    }
    assert not report.blocked
    assert set(by_key) == expected_keys | {"batch"}
    assert all(row["rule_id"] == "QA02_RAW" and row["result"] == "pass" for row in report.rows)
    assert sum(row["actual"]["evaluated_count"] for row in report.rows if row["object_key"] != "batch") == 19
    for file in files:
        row = by_key[f'file:{file["resource_id"]}:{file["file_sha256"]}:{file["parser_version"]}']
        assert row["actual"] == row["expected"] == {
            "evaluated_count": file["raw_count"], "violation_count": 0,
            "metrics": {
                "raw_count": file["raw_count"], "distinct_locator_count": file["raw_count"],
                "payload_mismatch_count": 0,
            },
        }
        assert row["affected_count"] == 0
        detail_rows(row)
    node = next(row for key, row in by_key.items() if "_vic_node:" in key)
    assert node["actual"]["metrics"]["distinct_locator_count"] == 4
    assert by_key["batch"]["actual"]["metrics"] == {
        "object_count": 7, "pass_count": 7, "limited_count": 0, "block_count": 0, "missing_count": 0,
    }


def test_postgres_qa02_finds_changed_payload_when_counts_match(connection, s0, frozen, tmp_path):
    loader = RawLoader(connection, dataset_kind="synthetic", sources=s0["sources"], files=s0["files"])
    loader.register()
    target = next(row for row in s0["rows"] if row["resource_id"].endswith("_nsw_crash"))
    altered = deepcopy(target)
    altered["payload"]["Crash ID"] = "changed-value"
    altered_id = None
    for row in s0["rows"]:
        accepted = loader.load_record(altered if row is target else row)
        if row is target:
            altered_id = accepted.raw_record_id

    report = check_raw(
        connection, frozen.as_dict(), s0["run_dir"].parents[2],
        evidence_dir=tmp_path / "qa-mismatch", producer_version="b11-postgres-test-v1",
    )
    assert report.blocked
    rows = [row for row in report.rows if row["object_key"] != "batch"]
    blocked = [row for row in rows if row["result"] == "block"]
    assert len(rows) == 7 and len(blocked) == 1
    row = blocked[0]
    assert row["object_key"] == f'file:{target["resource_id"]}:{target["file_sha256"]}:{target["parser_version"]}'
    assert row["actual"]["metrics"] == {
        "raw_count": 2, "distinct_locator_count": 2, "payload_mismatch_count": 1,
    }
    assert row["actual"]["evaluated_count"] == row["expected"]["evaluated_count"] == 2
    assert row["affected_count"] == row["actual"]["violation_count"] == 1
    assert row["evidence"]["reason_codes"] == ["RAW_PAYLOAD_MISMATCH"]
    details = detail_rows(row)
    mismatch = next(item for item in details if "RAW_PAYLOAD_MISMATCH" in item.get("reason_codes", []) and "row_locator" in item)
    assert mismatch["row_locator"] == target["row_locator"]
    assert mismatch["raw_record_id"] == str(altered_id)
    assert mismatch["expected"] == target["payload"]
    assert mismatch["actual"]["payload"] == altered["payload"]
    assert report.rows[-1]["actual"]["metrics"] == {
        "object_count": 7, "pass_count": 6, "limited_count": 0, "block_count": 1, "missing_count": 0,
    }
