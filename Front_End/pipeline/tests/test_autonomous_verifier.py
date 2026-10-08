from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from verify_autonomous_sources import Checks, GeographyVerifier, GetOnlyAPI, HashBag, _fact, compare_periods, verify, verify_blocked


def test_exact_integer_and_unavailable_comparison_has_no_tolerance():
    checks = Checks()
    for actual in (True, 1.0, "1", None, 2):
        checks.equal("metric", actual, 1)
    checks.equal("unknown", 0, None)
    checks.equal("exact", 1, 1)
    assert checks.report()["failed"] == 6
    assert checks.report()["passed"] == 1


def test_period_checker_rejects_duplicates_missing_months_and_null_to_zero():
    checks = Checks()
    expected = {"2024-01": {"crash_count": 1, "fatal_crash_count": 0, "fatalities": None, "casualties": None}}
    actual = [{"year": 2024, "month": 1, "crash_count": 1, "fatal_crash_count": 0, "fatalities": 0, "casualties": None}] * 2
    compare_periods(checks, "months", actual, expected, True)
    failed = {row["check"] for row in checks.rows if not row["passed"]}
    assert failed == {"months.unique_periods", "months.2024-01.fatalities"}
    empty = Checks()
    compare_periods(empty, "months", [], expected, True)
    assert any(row["check"] == "months.periods" and not row["passed"] for row in empty.rows)


def test_key_and_fact_hashes_detect_reassigned_records_despite_same_total():
    first, reversed_order, changed = HashBag(), HashBag(), HashBag()
    rows = [{"key": {"A": "1", "B": "01"}, "fatalities": 1}, {"key": {"A": "2", "B": "01"}, "fatalities": 0}]
    for row in rows:
        first.add(row)
    for row in reversed(rows):
        reversed_order.add(row)
    for index, row in enumerate(rows):
        changed.add({**row, "fatalities": index})
    assert first.result() == reversed_order.result()
    assert first.result()["rows"] == changed.result()["rows"]
    assert first.result()["sha256"] != changed.result()["sha256"]


def test_complete_composite_keys_can_reorder_but_not_drop_parent_component():
    parent = {"role": "events", "grain": "crash", "key": ["REPORT_ID"]}
    unit = {"role": "vehicles", "grain": "unit", "key": ["Unit No", "REPORT_ID"]}
    row = {"raw_key": ["2", "A"], "unit_type": "Bus", "count_eligible": True, "declared_casualties": 0,
           "relations": {"events": '["A"]'}}
    key, fact = _fact("unit", row, unit, {"events": parent, "vehicles": unit})
    assert key == {"REPORT_ID": "A", "Unit No": "2"}
    assert fact["relations"] == {"crash": {"REPORT_ID": "A"}}
    with pytest.raises(ValueError, match="complete source key"):
        _fact("unit", {**row, "raw_key": ["2"]}, unit, {"events": parent})


class Rows:
    def __init__(self, value):
        self.value = value
    def fetchone(self):
        return self.value
    def fetchall(self):
        return self.value


class BlockedDatabase:
    def __init__(self, job, changed_release=False, registered=False):
        self.job, self.changed, self.registered, self.statements = job, changed_release, registered, []
        self.before = {"id": UUID(int=1), "sources": {"official_nsw": "batch-nsw"}}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def transaction(self):
        return self
    def execute(self, sql, params=None):
        self.statements.append(sql)
        assert sql.startswith(("SELECT", "SET TRANSACTION")), "Verifier attempted a write"
        if sql.startswith("SET"):
            return Rows(None)
        if "SELECT * FROM jobs" in sql:
            return Rows(self.job)
        if "FROM batches" in sql:
            return Rows({"n": 0})
        if "FROM agent_sessions" in sql:
            return Rows({"id": UUID(int=3), "checkpoint": {"contract": {"source": {"source_id": "test"}, "resources": []}}})
        if "FROM attempts" in sql:
            return Rows({"started": self.job["created_at"]})
        if "FROM current_release" in sql:
            return Rows({**self.before, "id": UUID(int=2)} if self.changed else self.before)
        if "FROM releases" in sql:
            return Rows(self.before)
        if "FROM agent_steps" in sql:
            return Rows([])
        if "FROM adapter_versions" in sql:
            return Rows([{"id": "registered"}] if self.registered else [])
        raise AssertionError(sql)


def blocked_job():
    now = datetime.now(timezone.utc)
    return {"id": UUID(int=4), "status": "needs_input", "created_at": now, "updated_at": now, "batch_id": None, "release_id": None,
            "result": None, "files": [{"sha256": "official-hash"}]}


def test_blocked_verifier_proves_no_registration_and_unchanged_release():
    job = blocked_job(); checks = Checks()
    result = verify_blocked(BlockedDatabase(job), job, {"anomalies": [{"occurrence_date": "0002-02-14"}]}, checks)
    assert checks.report()["failed"] == 0
    assert result["candidate_registered"] is False
    assert result["candidate_published"] is False
    for changed, registered in ((True, False), (False, True)):
        failed = Checks()
        verify_blocked(BlockedDatabase(job, changed, registered), job, {}, failed)
        assert failed.report()["failed"] > 0


def test_main_verification_sets_database_read_only_and_uses_get_only(tmp_path):
    job = blocked_job(); conn = BlockedDatabase(job)
    oracle = tmp_path / "oracle.json"
    oracle.write_text(json.dumps({"oracle_version": 2, "state": "tas", "input_upload_sha256": "official-hash"}))
    args = SimpleNamespace(oracle=oracle, state="tas", job_id=job["id"], expect="blocked", before_release_id=None, via_website=True)
    calls = []
    def get(path):
        calls.append(path)
        return {"status": "needs_input"}
    with patch("arsia_pipeline.store.connect", return_value=conn), patch.object(GetOnlyAPI, "get", side_effect=get):
        result = verify(args)
    assert result["status"] == "passed"
    assert conn.statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert calls == ["/jobs/" + str(job["id"])]
    assert result["oracle_is_model_evidence"] is False


def geography_fixture(tmp_path, mapped=True):
    path = tmp_path / "geo.jsonl"
    values = [{"key": {"ID": "a"}, "coordinates": [149.123, -35.456], "status": "available"},
              {"key": {"ID": "b"}, "coordinates": None, "status": "unknown"}]
    path.write_text("".join(json.dumps(value) + "\n" for value in values))
    oracle = {"geography": {"records_path": str(path), "records_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "record_count": 2, "tolerance_degrees": 1e-7, "status_counts": {"available": 1, "unknown": 1}}}
    contract = {"resources": [{"grain": "crash", "mapping": {"geography": {"x_field": "x", "y_field": "y", "crs": "EPSG:4326"}} if mapped else {}}]}
    return GeographyVerifier(oracle, tmp_path / "oracle.json", contract)


def test_geography_accepts_only_documented_float_tolerance_and_matches_keys(tmp_path):
    geo = geography_fixture(tmp_path)
    try:
        geo.inspect({"ID": "a"}, {"coordinates": [149.123 + 5e-8, -35.456], "geography_status": "available", "coordinate_crs": "EPSG:4326"})
        geo.inspect({"ID": "b"}, {"coordinates": None, "geography_status": "unknown"})
        result = geo.result()
        assert result["status"] == "verified"
        assert not any(result["errors"].values())
        assert result["actual_status_counts"] == result["expected_status_counts"]
    finally:
        geo.close()


def test_geography_cannot_swap_axes_duplicate_keys_or_invent_missing_points(tmp_path):
    geo = geography_fixture(tmp_path)
    try:
        geo.inspect({"ID": "a"}, {"coordinates": [-35.456, 149.123], "geography_status": "available", "coordinate_crs": "EPSG:4326"})
        geo.inspect({"ID": "a"}, {"coordinates": [149.123, -35.456], "geography_status": "available", "coordinate_crs": "EPSG:4326"})
        geo.inspect({"ID": "b"}, {"coordinates": [149.123, -35.456], "geography_status": "available", "coordinate_crs": "EPSG:4326"})
        errors = geo.result()["errors"]
        assert errors["coordinate_difference_exceeds_tolerance"] == 1
        assert errors["duplicate_key"] == 1
        assert errors["missing_source_has_coordinates"] == 1
    finally:
        geo.close()


def test_omitted_optional_geo_is_not_verified_without_failing_crash_acceptance(tmp_path):
    geo = geography_fixture(tmp_path, mapped=False)
    try:
        for key in ("a", "b"):
            geo.inspect({"ID": key}, {"coordinates": None, "geography_status": "unsupported"})
        result = geo.result()
        assert result["status"] == "not_verified"
        assert not any(result["errors"].values())
        assert result["actual_status_counts"] == {"unsupported": 2}
    finally:
        geo.close()
