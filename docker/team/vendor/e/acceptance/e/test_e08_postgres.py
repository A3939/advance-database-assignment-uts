"""Additional AT08–15 checks through the installed B runner."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil

import pytest

if "AC_TEST_RUN" not in os.environ:
    pytest.skip("Run the isolated E acceptance verifier", allow_module_level=True)

import psycopg
from arsia_d05 import TrendRequest, query_trend
from arsia_d06 import SeverityRequest, query_severity
from arsia_d07 import MapRequest, query_map
from arsia_ingest.build import s8_request
from arsia_ingest.manifest import REQUIRED_CHECKS, digest_inventory, freeze_manifest
from arsia_ingest.pipeline import prepare
from arsia_ingest.recovery import recover_run
from arsia_ingest.runner import ModuleConnection, run_build
from e_acceptance_expected import crashes, map_coverage, metrics, qa_objects, trends
from test_at10_rule_postgres import known_n2_request
from test_full_build_postgres import (
    LostCommitReply, ROOT, batch_rows, connect, current, deployed,
    private_database, request_factory, run,
)


def pointer(connection):
    return connection.execute(
        "SELECT batch_id,switched_at FROM meta.current_release "
        "WHERE dataset_kind='synthetic'"
    ).fetchone()


def record(result, case, **facts):
    path = Path(result["evidence_ref"]) / "e-acceptance.json"
    path.write_text(json.dumps({"case": case, "batch_id": result["batch_id"],
                               **facts}, indent=2, default=str) + "\n", encoding="utf-8")


def reversed_objects(value):
    if isinstance(value, dict):
        return {key: reversed_objects(item) for key, item in reversed(value.items())}
    if isinstance(value, list):
        return [reversed_objects(item) for item in value]
    return value


@pytest.mark.parametrize("change", ["object_key_order", "archive_directory"])
def test_at08_provenance_and_object_order_keep_exact_pointer(request_factory, tmp_path, change):
    original = request_factory()
    baseline = run(original)
    with connect() as connection:
        before_pointer = pointer(connection)
        before_rows = batch_rows(connection, baseline["batch_id"])
        raw_before = connection.execute("SELECT to_jsonb(r) FROM raw.record r ORDER BY raw_record_id").fetchall()
    candidate = dict(original)
    value = candidate["manifest"].as_dict()
    if change == "object_key_order":
        reordered = reversed_objects(value)
        assert reordered == value
        assert json.dumps(reordered) != json.dumps(value)
        candidate["manifest"] = freeze_manifest(reordered, project_root=ROOT,
                                                 inventory=candidate["inventory"])
    else:
        prepared = Path(original["prepared_run"])
        intake_root = prepared.parents[2]
        moved_root = tmp_path / "relocated-intake"
        shutil.copytree(intake_root, moved_root)
        candidate["prepared_run"] = moved_root / prepared.relative_to(intake_root)
        assert candidate["prepared_run"] != prepared
        assert candidate["manifest"].as_dict() == value
    repeated = run_build(**candidate).as_dict()
    assert repeated["result"] == "no_change", repeated
    assert repeated["batch_id"] == baseline["batch_id"]
    assert repeated["input_fingerprint"] == baseline["input_fingerprint"]
    with connect() as connection:
        assert pointer(connection) == before_pointer
        assert connection.execute("SELECT count(*) FROM meta.batch").fetchone() == (1,)
        assert batch_rows(connection, baseline["batch_id"]) == before_rows
        assert connection.execute("SELECT to_jsonb(r) FROM raw.record r ORDER BY raw_record_id").fetchall() == raw_before
    record(repeated, "AT08", change=change, outcome="no_change", pointer_unchanged=True,
           history_unchanged=True, raw_unchanged=True)


def test_at10_real_sql_byte_change_rebuilds_without_changing_inputs(request_factory, tmp_path):
    original = request_factory()
    baseline = run(original)
    with connect() as connection:
        before = batch_rows(connection, baseline["batch_id"])
    candidate = dict(original)
    project = tmp_path / "code-change"
    inventory = deepcopy(candidate["inventory"])
    paths = set(inventory["schema_files"])
    for component in inventory["components"].values():
        paths.update(component)
    for relative in paths:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    changed = project / candidate["fp1"].code_path
    original_sql = changed.read_text(encoding="utf-8")
    changed.write_text(original_sql + "\n-- AT10: change SQL bytes without changing its result.\n", encoding="utf-8")
    value = candidate["manifest"].as_dict()
    previous_codes = value["rules"]["code_files"]
    value["rules"].update(digest_inventory(project, inventory))
    differing = [new["path"] for old, new in zip(previous_codes, value["rules"]["code_files"], strict=True)
                 if old != new]
    assert differing == [candidate["fp1"].code_path]
    assert value["files"] == original["manifest"].as_dict()["files"]
    candidate["project_root"] = project
    candidate["manifest"] = freeze_manifest(value, project_root=project, inventory=inventory)
    # Deploy the changed SQL bytes too; this is not an invented digest.
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        assert owner.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ["AC_TEST_RUN"],)
        owner.execute(changed.read_text(encoding="utf-8"))
    try:
        result = run(candidate)
    finally:
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
            owner.execute(original_sql)
    assert result["input_fingerprint"] != baseline["input_fingerprint"]
    assert result["batch_id"] != baseline["batch_id"]
    assert result["previous_batch_id"] == baseline["batch_id"]
    with connect() as connection:
        assert current(connection) == result["batch_id"]
        assert batch_rows(connection, baseline["batch_id"]) == before
        assert connection.execute("SELECT count(*) FROM raw.record").fetchone() == (19,)
        assert connection.execute("SELECT count(*) FROM meta.batch").fetchone() == (2,)
        for table in ("canonical.crash", "canonical.unit", "dw.fact_crash"):
            rows = lambda batch: connection.execute(
                f"SELECT to_jsonb(t)-'batch_id' FROM {table} t WHERE batch_id=%s "
                "ORDER BY (to_jsonb(t)-'batch_id')::text", (batch,)).fetchall()
            assert rows(result["batch_id"]) == rows(baseline["batch_id"])
    record(result, "AT10", change="actual FP1 SQL comment bytes", changed_paths=differing,
           inputs_unchanged=True, old_batch_unchanged=True, metrics_unchanged=True)


def test_at10_rule_matches_independent_expected_known_counts(request_factory, deployed):
    original = request_factory()
    baseline = run(original)
    changed = known_n2_request(original)
    assert changed["manifest"].as_dict()["files"] == original["manifest"].as_dict()["files"]
    result = run(changed)
    assert result["input_fingerprint"] != baseline["input_fingerprint"]
    assert result["previous_batch_id"] == baseline["batch_id"]
    compared = {}
    with psycopg.connect(deployed) as reader:
        for variant, batch in (("s0", baseline["batch_id"]), ("known_n2", result["batch_id"])):
            expected = metrics(crashes(variant))
            rows = query_trend(ModuleConnection(reader), TrendRequest("synthetic", batch))
            actual = {field: sum(row[field] or 0 for row in rows) for field in expected}
            assert actual == expected
            compared[variant] = {"expected": expected, "actual": actual}
    record(result, "AT10", comparisons=compared, unchanged_native_files=True,
           scope="The independent E oracle is derived from contract 04, not the loader")


@pytest.mark.parametrize("variant", ["revised_n1", "delete_q2", "s8"])
def test_at09_at15_variants_match_independent_rows_keys_and_queries(request_factory, deployed, variant):
    baseline = run(request_factory())
    with connect() as connection:
        before = batch_rows(connection, baseline["batch_id"])
    if variant == "s8":
        evidence = Path(os.environ["AC_EVIDENCE_DIR"]) / "e08-s8-independent"
        prepared = prepare(ROOT / "tests/fixtures/s8/config.json", evidence / "intake")
        assert prepared["status"] == "prepared" and prepared["raw_count"] == 20
        candidate = s8_request(connect=connect, project_root=ROOT,
                               prepared_run=prepared["run_dir"], evidence_root=evidence / "build")
    else:
        candidate = request_factory(variant=variant)
    result = run(candidate)
    batch = result["batch_id"]
    assert result["previous_batch_id"] == baseline["batch_id"]
    assert result["input_fingerprint"] != baseline["input_fingerprint"]
    wanted = crashes(variant)
    expected_ids = {(row["source_id"], json.dumps([row["native_id"]])) for row in wanted}
    snapshot_files = candidate["manifest"].as_dict()["files"]
    assert sum(file["raw_count"] for file in snapshot_files) == {
        "revised_n1": 19, "delete_q2": 18, "s8": 20,
    }[variant]
    native_fields = {"syn_nsw": "Crash ID", "syn_vic": "ACCIDENT_NO",
                     "syn_qld": "Crash_Ref_Number", "syn_sa": "CRASH_ID"}
    with connect() as connection:
        assert current(connection) == batch
        assert batch_rows(connection, baseline["batch_id"]) == before
        canonical = connection.execute("""SELECT to_jsonb(c),r.resource_id,r.payload,l.resource_id
            FROM canonical.crash c JOIN raw.record r USING(raw_record_id)
            LEFT JOIN raw.record l ON l.raw_record_id=c.location_record_id WHERE c.batch_id=%s""",
            (batch,)).fetchall()
        actual = {(row[0]["source_id"], row[0]["crash_key"]): row for row in canonical}
        assert len(canonical) == len(expected_ids) and set(actual) == expected_ids
        facts = connection.execute("SELECT to_jsonb(f) FROM dw.fact_crash f WHERE batch_id=%s", (batch,)).fetchall()
        fact_rows = {(row[0]["source_id"], row[0]["crash_key"]): row[0] for row in facts}
        assert len(facts) == len(expected_ids) and set(fact_rows) == expected_ids
        for row in wanted:
            identity = (row["source_id"], json.dumps([row["native_id"]]))
            crash, resource, raw, location_resource = actual[identity]
            assert resource == row["resource_id"] and location_resource == row["location_resource"]
            assert raw[native_fields[row["source_id"]]] == row["native_id"]
            expected = {
                "release_scope": "s0", "occurrence_year": row["year"],
                "occurrence_month": row["month"], "occurrence_date": row["date"],
                "date_precision": row["precision"], "severity_code": row["severity"],
                "severity_definition_version": "syn-1", "is_fatal_crash": row["fatal"],
                "fatality_count": row["fatalities"], "casualty_count": row["casualties"],
                "fatal_crash_eligible": row["fatal"] is not None,
                "fatality_eligible": row["fatalities"] is not None,
                "casualty_eligible": row["casualties"] is not None,
                "map_eligible": row["latitude"] is not None,
                "location_crs": "EPSG:4326" if row["latitude"] is not None else None,
            }
            assert {key: crash[key] for key in expected} == expected
            fact_expected = {key: expected[key] for key in (
                "release_scope", "occurrence_year", "severity_code", "is_fatal_crash",
                "fatality_count", "casualty_count", "fatal_crash_eligible", "fatality_eligible",
                "casualty_eligible", "map_eligible")}
            fact_expected["month_id"] = row["year"] * 100 + row["month"] if row["month"] is not None else None
            assert {key: fact_rows[identity][key] for key in fact_expected} == fact_expected
            for field in ("latitude", "longitude"):
                expected_value = Decimal(row[field]) if row[field] is not None else None
                for stored in (crash, fact_rows[identity]):
                    assert (Decimal(str(stored[field])) if stored[field] is not None else None) == expected_value
        unit_rows = connection.execute("""SELECT u.source_id,u.crash_key,u.unit_key,u.unit_type_code,
            u.statistical_scope,u.count_eligible FROM canonical.unit u WHERE batch_id=%s""", (batch,)).fetchall()
        expected_units = {(row["source_id"], json.dumps([row["native_id"]]),
                           json.dumps([row["native_id"], unit]), "CAR",
                           "synthetic_traffic_unit" if row["source_id"] == "syn_nsw" else "synthetic_vehicle", True)
                          for row in wanted for unit in row["units"]}
        assert len(unit_rows) == len(expected_units) and set(unit_rows) == expected_units
        objects = qa_objects(snapshot_files, variant)
        qa = connection.execute("SELECT rule_id,object_key FROM qa.check_result WHERE batch_id=%s", (batch,)).fetchall()
        expected_qa = {(rule, key) for rule, keys in objects.items() for key in keys}
        assert len(qa) == len(expected_qa) and set(qa) == expected_qa
    comparisons = {}
    with psycopg.connect(deployed) as reader:
        shared = ModuleConnection(reader)
        for grain in ("year", "month"):
            rows = query_trend(shared, TrendRequest("synthetic", batch, grain=grain))
            expected = trends(variant, grain=grain)
            assert len(rows) == len(expected)
            assert {(row["source_id"], row["period_year"], row["period_month"]) for row in rows} == set(expected)
            for row in rows:
                target = expected[row["source_id"], row["period_year"], row["period_month"]]
                assert {key: row[key] for key in target} == target
            comparisons[grain] = rows
        coverage = query_map(shared, MapRequest("synthetic", batch)).coverage
        expected_coverage = map_coverage(wanted)
        assert {key: coverage[key] for key in expected_coverage} == expected_coverage
        severity = query_severity(shared, SeverityRequest("synthetic", batch))
        expected_groups = {}
        for row in wanted:
            key = (row["source_id"], row["severity"])
            expected_groups[key] = expected_groups.get(key, 0) + 1
        assert len(severity) == len(expected_groups)
        assert {(row["source_id"], row["severity_code"]): row["crash_count"] for row in severity} == expected_groups
    record(result, "AT15" if variant == "s8" else "AT09", variant=variant,
           expected_rows=wanted, actual_canonical=canonical, actual_facts=facts, actual_units=unit_rows,
           trend_comparisons=comparisons, expected_map=expected_coverage, actual_map=coverage,
           old_history_unchanged=True, qa_objects=len(expected_qa))


@pytest.mark.parametrize("rule", REQUIRED_CHECKS)
def test_at11_missing_object_preserves_published_baseline(request_factory, rule):
    baseline = run(request_factory())
    with connect() as connection:
        before_pointer = pointer(connection)
        before = batch_rows(connection, baseline["batch_id"])
    candidate = request_factory(analysis={"year_from": 2021, "year_to": 2024})
    original = candidate["modules"].publish
    connection = psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"])
    connection.execute("SET ROLE arsia_loader")
    candidate["connect"] = lambda: connection
    missing = []

    def omit(shared, context):
        # The owner only injects the fault. Every real callback runs as loader.
        connection.execute("RESET ROLE")
        row = connection.execute(
            "SELECT object_key FROM qa.check_result WHERE batch_id=%s AND rule_id=%s "
            "AND object_key<>'batch' ORDER BY object_key LIMIT 1", (context.batch_id, rule)
        ).fetchone()
        assert row is not None
        missing.append(row[0])
        assert connection.execute(
            "DELETE FROM qa.check_result WHERE batch_id=%s AND rule_id=%s AND object_key=%s",
            (context.batch_id, rule, row[0])).rowcount == 1
        assert connection.execute(
            "SELECT count(*) FROM qa.check_result WHERE batch_id=%s AND object_key='batch'",
            (context.batch_id,)).fetchone() == (7,)
        connection.execute("SET ROLE arsia_loader")
        assert connection.execute("SELECT current_user").fetchone() == ("arsia_loader",)
        return original.callback(shared, context)

    candidate["modules"] = replace(candidate["modules"], publish=replace(original, callback=omit))
    failed = run_build(**candidate).as_dict()
    assert failed["result"] == "failed" and failed["stage"] == "publish", failed
    assert failed["error_code"] == "PUBLICATION_QA_MISSING", failed
    with connect() as observer:
        assert pointer(observer) == before_pointer
        assert batch_rows(observer, baseline["batch_id"]) == before
        assert all(not value for value in batch_rows(observer, failed["batch_id"]).values())
        assert observer.execute("SELECT status FROM meta.batch WHERE batch_id=%s",
                                (failed["batch_id"],)).fetchone() == ("failed",)
    assert (Path(failed["evidence_ref"]) / "error.json").is_file()
    record(failed, "AT11", omitted_rule=rule, omitted_object=missing[0],
           all_summaries_present=True, old_pointer_unchanged=True, candidate_rolled_back=True)


def test_at12_real_disconnect_requires_recovery_then_whole_run_retry(request_factory):
    baseline = run(request_factory())
    with connect() as connection:
        before_pointer = pointer(connection)
        before = batch_rows(connection, baseline["batch_id"])
    candidate = request_factory(analysis={"year_from": 2021, "year_to": 2024})
    original = candidate["modules"].dw
    connection = connect()
    candidate["connect"] = lambda: connection

    def disconnect(shared, context):
        original.callback(shared, context)
        connection.close()
        raise ConnectionError("AT12 closed the real build connection after DW")

    candidate["modules"] = replace(candidate["modules"], dw=replace(original, callback=disconnect))
    failed = run_build(**candidate).as_dict()
    assert failed["result"] == "unknown_commit", failed
    assert (Path(failed["evidence_ref"]) / "error.json").is_file()
    with connect() as observer:
        assert pointer(observer) == before_pointer
        assert batch_rows(observer, baseline["batch_id"]) == before
        assert all(not value for value in batch_rows(observer, failed["batch_id"]).values())
        assert observer.execute("SELECT status FROM meta.batch WHERE batch_id=%s",
                                (failed["batch_id"],)).fetchone() == ("running",)
    blocked = run_build(**request_factory(analysis={"year_from": 2021, "year_to": 2024})).as_dict()
    assert blocked["result"] == "failed" and blocked["error_code"] == "RECOVERY_REQUIRED", blocked
    assert blocked["batch_id"] is None
    recovered = recover_run(connect=connect, run_dir=failed["evidence_ref"],
                            evidence_root=Path(failed["evidence_ref"]).parent / "recovery").as_dict()
    assert recovered["resolution"] == "failed", recovered
    assert recovered["action"] == "closed_abandoned_run"
    retried = run(request_factory(analysis={"year_from": 2021, "year_to": 2024}))
    assert retried["batch_id"] != failed["batch_id"]
    with connect() as observer:
        assert current(observer) == retried["batch_id"]
        assert batch_rows(observer, baseline["batch_id"]) == before
        assert observer.execute("SELECT status FROM meta.batch WHERE batch_id=%s",
                                (failed["batch_id"],)).fetchone() == ("failed",)
        assert observer.execute("SELECT count(*) FROM meta.batch").fetchone() == (3,)
    record(retried, "AT12", disconnected_attempt=failed["batch_id"],
           recovery=recovered["resolution"], retry_is_new_batch=True, old_history_unchanged=True,
           fault="Real client connection closed after DW; no server outage was simulated")


def test_at12_superseded_commit_acknowledgement_never_restores_old_pointer(request_factory):
    candidate = request_factory()
    candidate["connect"] = LostCommitReply
    uncertain = run_build(**candidate).as_dict()
    assert uncertain["result"] == "unknown_commit", uncertain
    with connect() as connection:
        before = batch_rows(connection, uncertain["batch_id"])
    newer = run(request_factory(analysis={"year_from": 2021, "year_to": 2024}))
    with connect() as connection:
        newer_pointer = pointer(connection)
    recovered = recover_run(connect=connect, run_dir=uncertain["evidence_ref"],
                            evidence_root=Path(uncertain["evidence_ref"]).parent / "recovery").as_dict()
    assert recovered["resolution"] == "succeeded", recovered
    assert recovered["current_batch_id"] == newer["batch_id"]
    with connect() as connection:
        assert pointer(connection) == newer_pointer
        assert batch_rows(connection, uncertain["batch_id"]) == before
        assert connection.execute("SELECT status FROM meta.batch ORDER BY started_at").fetchall() == [
            ("succeeded",), ("succeeded",)]
    record(newer, "AT12", recovered_old_batch=uncertain["batch_id"],
           resolution=recovered["resolution"], newer_pointer_unchanged=True,
           old_success_unchanged=True)
