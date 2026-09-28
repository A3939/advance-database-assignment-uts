"""AT10 changes a declared synthetic rule while native bytes stay fixed."""
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

if "AC_TEST_RUN" not in os.environ:
    pytest.skip("Use the private PostgreSQL verifier", allow_module_level=True)

import psycopg
from arsia_d05 import TrendRequest, query_trend
from arsia_ingest.manifest import freeze_manifest
from arsia_ingest.runner import ModuleConnection, run_build
from test_full_build_postgres import (
    ROOT, batch_rows, connect, current, deployed, private_database, request_factory, run,
)

REASON = "AT10 fictional NSW rule: native missing severity means non-fatal; people counts remain unknown."


def known_n2_request(request):
    candidate = dict(request)
    value = candidate["manifest"].as_dict()
    mapping = next(m for m in value["rules"]["mappings"] if m["id"] == "syn_nsw_crash_mapping")
    mapping["version"] = "syn-at10-nsw-v2"
    mapping["content"].update(missing_severity_code="N", missing_severity_reason=REASON)
    mapping["content"]["severity_code"]["native_missing"] = "N"
    contract = next(c for c in value["rules"]["contracts"] if c["id"] == "syn_nsw_crash")
    contract["version"] = "s0-native-at10-v2"
    contract["content"]["semantics"]["common_rules"]["indicator_eligibility"] = REASON
    candidate["manifest"] = freeze_manifest(value, project_root=ROOT, inventory=candidate["inventory"])
    candidate["supported_mappings"] = value["rules"]["mappings"]
    return candidate


def test_at10_rule_rebuild_changes_only_n2_classification(request_factory, deployed):
    request = request_factory()
    first = run(request)
    with connect() as connection:
        before = batch_rows(connection, first["batch_id"])
    changed = known_n2_request(request)
    assert changed["manifest"].as_dict()["files"] == request["manifest"].as_dict()["files"]
    second = run(changed)
    assert second["input_fingerprint"] != first["input_fingerprint"]
    assert second["previous_batch_id"] == first["batch_id"]
    with connect() as connection:
        assert current(connection) == second["batch_id"]
        assert batch_rows(connection, first["batch_id"]) == before
        assert connection.execute("SELECT count(*) FROM raw.record").fetchone() == (19,)
        assert connection.execute("SELECT count(*) FROM qa.check_result WHERE batch_id=%s",
                                  (second["batch_id"],)).fetchone() == (63,)
        old, new = [connection.execute(
            "SELECT severity_raw,severity_code,is_fatal_crash,fatality_count,casualty_count,"
            "fatal_crash_eligible,fatality_eligible,casualty_eligible,quality_notes "
            "FROM canonical.crash WHERE batch_id=%s AND source_id='syn_nsw' "
            "AND crash_key=rv.encode_business_key('0002')", (batch,)).fetchone()
            for batch in (first["batch_id"], second["batch_id"])]
        assert old[:8] == (None, "__MISSING__", None, None, None, False, False, False)
        assert new[:8] == (None, "N", False, None, None, True, False, False)
        assert new[8]["severity_rule"] == {"code": "N", "reason": REASON, "mapping_version": "syn-at10-nsw-v2"}
        assert connection.execute("SELECT severity_code FROM dw.fact_crash WHERE batch_id=%s "
                                  "AND source_id='syn_nsw' AND crash_key=rv.encode_business_key('0002')",
                                  (second["batch_id"],)).fetchone() == ("N",)
        assert connection.execute("SELECT count(*) FROM dw.dim_severity WHERE batch_id=%s "
                                  "AND severity_code='__MISSING__'", (second["batch_id"],)).fetchone() == (3,)
    actual = []
    with psycopg.connect(deployed) as reader:
        for batch in (first["batch_id"], second["batch_id"]):
            rows = query_trend(ModuleConnection(reader), TrendRequest("synthetic", batch))
            actual.append(tuple(sum(row[field] or 0 for row in rows) for field in (
                "crash_count", "fatal_crash_count", "fatality_count", "casualty_count",
                "fatal_crash_known_count", "fatality_known_count", "casualty_known_count")))
    assert actual == [(6, 2, 3, 7, 5, 5, 5), (6, 2, 3, 7, 6, 5, 5)]
    repeated = run_build(**known_n2_request(request)).as_dict()
    assert repeated["result"] == "no_change" and repeated["batch_id"] == second["batch_id"]
    (Path(second["evidence_ref"]) / "at10-rule.json").write_text(json.dumps({
        "case": "AT10", "baseline_batch_id": first["batch_id"], "changed_batch_id": second["batch_id"],
        "unchanged_native_files": True, "old_history_preserved": True, "actual": actual,
        "scope": "Explicit synthetic-only rule; official missing-value rules are unchanged.",
    }, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("fault", ["classification", "reason"])
def test_at10_independent_c10_rejects_wrong_rule_result(request_factory, fault):
    baseline = run(request_factory())
    candidate = known_n2_request(request_factory())
    original = candidate["modules"].project

    def corrupt(connection, context):
        original.callback(connection, context)
        with connection.cursor() as cursor:
            assignment = ("severity_code='F',is_fatal_crash=true" if fault == "classification"
                          else "quality_notes=quality_notes-'severity_rule'")
            cursor.execute("UPDATE pg_temp.arsia_i_crash SET " + assignment +
                           " WHERE source_id='syn_nsw' AND crash_key=rv.encode_business_key('0002')")
            assert cursor.rowcount == 1

    candidate["modules"] = replace(candidate["modules"], project=replace(original, callback=corrupt))
    failed = run_build(**candidate).as_dict()
    assert (failed["result"], failed["stage"], failed["error_code"]) == ("failed", "qa_c", "C10_BLOCK"), failed
    with connect() as connection:
        assert current(connection) == baseline["batch_id"]
        assert all(not rows for rows in batch_rows(connection, failed["batch_id"]).values())
