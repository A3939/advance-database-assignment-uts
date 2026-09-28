"""E07 checks real S0 builds against document 04, not producer calculations."""
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from http.server import ThreadingHTTPServer
from importlib.resources import files
import importlib.util
import json
import os
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

if "AC_TEST_RUN" not in os.environ:
    pytest.skip("Use the E acceptance replay and its private database", allow_module_level=True)

import psycopg

from arsia_d05 import TrendRequest, query_trend
from arsia_d06 import SeverityRequest, query_severity
from arsia_d07 import MapRequest, query_map
from arsia_d08 import UnitRequest, query_units
from arsia_d09 import DashboardFilters, load_dashboard
from arsia_d09.web import make_handler, render_page
from arsia_ingest.runner import ModuleConnection, run_build
from arsia_ingest.pipeline import prepare
from e_acceptance_expected import crashes, load_expected, map_coverage, qa_objects, trends
from test_full_build_postgres import (
    batch_rows, connect, current, deployed, private_database, request_factory, run,
)


def record(name, value):
    root = Path(os.environ["AC_EVIDENCE_DIR"]) / "e07"
    root.mkdir(exist_ok=True)
    (root / (name + ".json")).write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def reader_dsn(deployed):
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        owner.execute("SET LOCAL ROLE arsia_migrator")
        owner.execute(files("arsia_d09").joinpath("sql/d09_context.sql").read_text(encoding="utf-8"))
    return deployed


def test_e07_full_s0_layers_rows_lineage_and_independent_qa(request_factory):
    request = request_factory()
    result = run(request)
    batch = result["batch_id"]
    expected = load_expected()
    with connect() as connection:
        counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in expected["layers"]}
        assert counts == expected["layers"]
        raw_counts = dict(connection.execute("SELECT resource_id,count(*) FROM raw.record GROUP BY resource_id").fetchall())
        assert raw_counts == {key: value["rows"] for key, value in expected["resources"].items()}
        entries = connection.execute("""SELECT to_jsonb(c),r.resource_id,r.payload,l.resource_id,l.payload,l.row_locator
            FROM canonical.crash c JOIN raw.record r USING(raw_record_id)
            LEFT JOIN raw.record l ON l.raw_record_id=c.location_record_id
            WHERE c.batch_id=%s""", (batch,)).fetchall()
        actual = {}
        keys = set()
        for crash, resource, raw, location_resource, location_raw, locator in entries:
            identity = (crash["source_id"], raw[expected["resources"][resource]["native_key"]])
            assert identity not in actual
            keys.add((crash["source_id"], crash["release_scope"], crash["crash_key"]))
            actual[identity] = (crash, resource, location_resource)
            if location_resource == "syn_vic_node":
                assert location_raw["ACCIDENT_NO"] == identity[1]
                assert location_raw["NODE_ID"] == "NODE01" and locator == "csv:1"
            elif location_resource is not None:
                assert crash["location_record_id"] == crash["raw_record_id"]
        assert len(keys) == 6
        expected_identity = {(r["source_id"], r["native_id"]) for r in crashes()}
        assert set(actual) == expected_identity
        facts = connection.execute("""SELECT to_jsonb(f),r.resource_id,r.payload FROM dw.fact_crash f
            JOIN canonical.crash c USING(batch_id,source_id,release_scope,crash_key)
            JOIN raw.record r ON r.raw_record_id=c.raw_record_id WHERE f.batch_id=%s""", (batch,)).fetchall()
        fact_by_identity = {(fact["source_id"], raw[expected["resources"][resource]["native_key"]]): fact
                            for fact, resource, raw in facts}
        assert len(facts) == 6 and set(fact_by_identity) == expected_identity
        for wanted in crashes():
            row, resource, location_resource = actual[wanted["source_id"], wanted["native_id"]]
            assert resource == wanted["resource_id"] and location_resource == wanted["location_resource"]
            assert row["crash_key"] == json.dumps([wanted["native_id"]])
            compared = {
                "release_scope": "s0", "occurrence_year": wanted["year"],
                "occurrence_month": wanted["month"], "occurrence_date": wanted["date"],
                "date_precision": wanted["precision"], "severity_code": wanted["severity"],
                "severity_definition_version": "syn-1", "is_fatal_crash": wanted["fatal"],
                "fatality_count": wanted["fatalities"], "casualty_count": wanted["casualties"],
                "fatal_crash_eligible": wanted["fatal"] is not None,
                "fatality_eligible": wanted["fatalities"] is not None,
                "casualty_eligible": wanted["casualties"] is not None,
                "map_eligible": wanted["latitude"] is not None,
                "location_crs": "EPSG:4326" if wanted["latitude"] is not None else None,
            }
            assert {key: row[key] for key in compared} == compared
            for field in ("latitude", "longitude"):
                assert (Decimal(str(row[field])) if row[field] is not None else None) == (
                    Decimal(wanted[field]) if wanted[field] is not None else None)
            if not row["map_eligible"]:
                assert row["location_record_id"] is None and row["quality_notes"]
            fact = fact_by_identity[wanted["source_id"], wanted["native_id"]]
            fact_expected = {key: value for key, value in compared.items() if key in fact}
            fact_expected["month_id"] = wanted["year"] * 100 + wanted["month"] if wanted["month"] is not None else None
            assert {key: fact[key] for key in fact_expected} == fact_expected
            assert fact["crash_key"] == row["crash_key"]
            for field in ("latitude", "longitude"):
                assert (Decimal(str(fact[field])) if fact[field] is not None else None) == (
                    Decimal(wanted[field]) if wanted[field] is not None else None)
        units = connection.execute("""SELECT u.source_id,r.payload,c.source_id,p.payload,u.unit_type_code,
            u.statistical_scope,u.count_eligible,u.unit_key,u.crash_key FROM canonical.unit u
            JOIN raw.record r ON r.raw_record_id=u.raw_record_id
            JOIN canonical.crash c ON (c.batch_id,c.source_id,c.release_scope,c.crash_key)=
                (u.batch_id,u.source_id,u.release_scope,u.crash_key)
            JOIN raw.record p ON p.raw_record_id=c.raw_record_id WHERE u.batch_id=%s""", (batch,)).fetchall()
        actual_units = set()
        for source, raw, parent_source, parent, unit_type, scope, eligible, unit_key, parent_key in units:
            native = "Crash ID" if source == "syn_nsw" else "ACCIDENT_NO"
            unit_id = "Traffic unit ID" if source == "syn_nsw" else "VEHICLE_ID"
            assert source == parent_source and raw[native] == parent[native]
            assert unit_key == json.dumps([raw[native], raw[unit_id]])
            assert parent_key == json.dumps([parent[native]])
            assert (unit_type, eligible) == ("CAR", True)
            assert scope == ("synthetic_traffic_unit" if source == "syn_nsw" else "synthetic_vehicle")
            actual_units.add((source, raw[native], raw[unit_id]))
        assert actual_units == {(r["source_id"], r["native_id"], unit) for r in crashes() for unit in r["units"]}
        assert connection.execute("SELECT count(*) FROM raw.record WHERE resource_id='syn_vic_node'").fetchone() == (4,)
        qa = connection.execute("""SELECT rule_id,object_key,result,affected_count,actual,expected,evidence
            FROM qa.check_result WHERE batch_id=%s ORDER BY rule_id,object_key""", (batch,)).fetchall()
        coverage = qa_objects(request["manifest"].as_dict()["files"])
        assert {(r[0], r[1]) for r in qa} == {(rule, key) for rule, keys in coverage.items() for key in keys}
        assert dict(Counter(r[0] for r in qa)) == expected["qa_rows"]
        for rule, key, status, affected, observed, required, evidence in qa:
            limited = rule == "QA07_LOCATION" and key in expected["limited_objects"]
            assert status == ("limited" if limited else "pass")
            assert affected == (2 if limited and key == "batch" else 1 if limited else 0)
            assert observed["violation_count"] == required["violation_count"] == 0
            assert evidence["producer_version"] and evidence["references"]
            if rule == "QA07_LOCATION" and key != "batch":
                _, source, year = key.split(":")
                subset = [r for r in crashes() if r["source_id"] == source and r["year"] == int(year)]
                points = map_coverage(subset)
                assert observed["metrics"] == {
                    "crash_count": points["crash_count"], "map_count": points["point_count"],
                    "unmapped_count": points["crash_count"] - points["point_count"], "invalid_eligible_count": 0,
                }
    record("at02-07-s0", {"build": result, "layers": counts, "canonical": entries, "facts": facts, "units": units, "qa": qa})


@pytest.mark.parametrize("grain", ["year", "month"])
def test_e07_queries_match_every_independent_source_period(request_factory, reader_dsn, grain):
    result = run(request_factory())
    with psycopg.connect(reader_dsn) as reader:
        shared = ModuleConnection(reader)
        actual = query_trend(shared, TrendRequest("synthetic", result["batch_id"], grain=grain))
        expected = trends(grain=grain)
        assert {(r["source_id"], r["period_year"], r["period_month"]) for r in actual} == set(expected)
        for row in actual:
            wanted = expected[row["source_id"], row["period_year"], row["period_month"]]
            assert {key: row[key] for key in wanted} == wanted
            assert row["coverage_basis"] and str(row["batch_id"]) == result["batch_id"]
        severity = query_severity(shared, SeverityRequest("synthetic", result["batch_id"]))
        assert {(r["source_id"], r["severity_code"]): r["crash_count"] for r in severity} == dict(
            Counter((r["source_id"], r["severity"]) for r in crashes()))
        assert all(r["definition_version"] == "syn-1" and r["definition_text"] for r in severity)
        mapping = query_map(shared, MapRequest("synthetic", result["batch_id"]))
        assert {key: mapping.coverage[key] for key in map_coverage(crashes())} == map_coverage(crashes())
        assert {(r["source_id"], r["latitude"], r["longitude"]) for r in mapping.points} == {
            (r["source_id"], Decimal(r["latitude"]), Decimal(r["longitude"])) for r in crashes() if r["latitude"] is not None}
        units = query_units(shared, UnitRequest("synthetic", result["batch_id"]))
        assert {(r["source_id"], r["statistical_scope"], r["unit_type_code"]): r["unit_count"] for r in units} == {
            ("syn_nsw", "synthetic_traffic_unit", "CAR"): 3, ("syn_vic", "synthetic_vehicle", "CAR"): 3}
    record("at16-" + grain, {"build": result, "trend": actual, "severity": severity,
                            "points": mapping.points, "coverage": mapping.coverage, "units": units})


def test_e07_at16_n2_only_query_subsample_keeps_unknowns(request_factory, reader_dsn):
    result = run(request_factory())
    batch = result["batch_id"]
    # This rolled-back module fixture is not a second published dataset.
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        try:
            owner.execute("""DELETE FROM dw.fact_crash WHERE batch_id=%s
                AND NOT(source_id='syn_nsw' AND month_id IS NULL)""", (batch,))
            owner.execute("SET LOCAL ROLE arsia_reader")
            shared = ModuleConnection(owner)
            trend = query_trend(shared, TrendRequest("synthetic", batch, source_ids=("syn_nsw",), year_from=2020, year_to=2020))
            assert len(trend) == 1 and trend[0]["crash_count"] == 1
            for metric in ("fatal_crash", "fatality", "casualty"):
                assert trend[0][metric + "_known_count"] == 0 and trend[0][metric + "_count"] is None
            coverage = query_map(shared, MapRequest("synthetic", batch, source_ids=("syn_nsw",))).coverage
            assert (coverage["crash_count"], coverage["point_count"], coverage["coverage_percentage"]) == (1, 0, Decimal("0.00"))
            record("at16-n2-module-only", {"batch_id": batch, "scope": "Uncommitted N2-only query fixture; always rolled back", "trend": trend, "coverage": coverage})
        finally:
            owner.rollback()
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM dw.fact_crash WHERE batch_id=%s", (batch,)).fetchone() == (6,)


def test_e07_at16_real_http_no_publication_empty_year_and_invalid_month(request_factory, reader_dsn):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(reader_dsn, False))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    try:
        with urlopen(url, timeout=10) as response:
            initial = response.read().decode("utf-8")
        assert "D09_NO_PUBLICATION" in initial and "no successful synthetic release is published" in initial
        result = run(request_factory())
        with urlopen(url, timeout=10) as response:
            body = response.read().decode("utf-8")
        assert result["batch_id"] in body and "66.67%" in body and "syn-1" in body
        assert "NULL" in body and "Known counts" in body and "synthetic" in body
        for source in load_expected()["sources"]:
            assert source in body
        with psycopg.connect(reader_dsn) as reader:
            empty = load_dashboard(reader, DashboardFilters("synthetic", year_from=2024, year_to=2024))
            assert len(empty.trend) == 3
            assert all(r["crash_count"] == 0 and r["fatality_count"] is None for r in empty.trend)
            assert empty.map.coverage["coverage_percentage"] is None and not empty.map.points
            assert not empty.severity and not empty.units
            empty_html = render_page(empty.filters, empty)
        with urlopen(url + "?year_from=2024&year_to=2024", timeout=10) as response:
            http_empty = response.read().decode("utf-8")
        assert result["batch_id"] in http_empty
        assert 'Map coverage</span><strong><span class="null">NULL</span></strong>' in http_empty
        assert 'Crashes</span><strong>0</strong>' in http_empty
        with pytest.raises(HTTPError) as error:
            urlopen(url + "?months=13", timeout=10)
        assert error.value.code == 400
        assert "D09_ARGUMENT" in error.value.read().decode("utf-8")
        record("at16-http", {"batch_id": result["batch_id"], "no_publication": initial,
                             "s0_html": body, "empty_html": empty_html, "month13_status": 400})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_e07_at01_schema_and_unchanged_reader_boundary(request_factory, reader_dsn):
    result = run(request_factory())
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        schemas = ["meta", "raw", "rv", "canonical", "dw", "qa"]
        tables = owner.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema=ANY(%s) AND table_type='BASE TABLE'", (schemas,)).fetchone()[0]
        columns = owner.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema=ANY(%s)", (schemas,)).fetchone()[0]
        fks = owner.execute("SELECT count(*) FROM information_schema.table_constraints WHERE table_schema=ANY(%s) AND constraint_type='FOREIGN KEY'", (schemas,)).fetchone()[0]
        assert (tables, columns, fks) == (17, 129, 30)
        with pytest.raises(psycopg.errors.CheckViolation):
            owner.execute("UPDATE canonical.crash SET location_crs=NULL WHERE batch_id=%s AND map_eligible", (result["batch_id"],))
        owner.rollback()
    with psycopg.connect(reader_dsn) as reader:
        assert reader.execute("SELECT current_user,session_user").fetchone() == ("arsia_reader", "arsia_reader")
        for statement in ("SELECT payload FROM raw.record", "UPDATE published.current_release SET switched_at=clock_timestamp()"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                reader.execute(statement)
            reader.rollback()
        assert str(load_dashboard(reader, DashboardFilters("synthetic")).release.batch_id) == result["batch_id"]
    record("at01", {"tables": tables, "columns": columns, "foreign_keys": fks,
                    "map_without_crs_rejected": True, "reader_select_and_write_rejected": True})


@pytest.mark.parametrize("fault", ["missing_fact", "compensating_counts", "eligibility"])
def test_e07_at06_real_reconciliation_rejects_damaged_candidate(request_factory, fault):
    baseline = run(request_factory())
    with connect() as connection:
        before = batch_rows(connection, baseline["batch_id"])
    request = request_factory(analysis={"year_from": 2020, "year_to": 2023})
    connection = psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"])
    connection.execute("SET ROLE arsia_loader")
    request["connect"] = lambda: connection
    original = request["modules"].qa_d
    def corrupt(shared, context):
        connection.execute("RESET ROLE")
        if fault == "missing_fact":
            connection.execute("DELETE FROM dw.fact_crash WHERE batch_id=%s AND source_id='syn_qld' AND occurrence_year=2021", (context.batch_id,))
        elif fault == "compensating_counts":
            connection.execute("""UPDATE dw.fact_crash SET casualty_count=CASE source_id
                WHEN 'syn_nsw' THEN casualty_count-1 ELSE casualty_count+1 END
                WHERE batch_id=%s AND is_fatal_crash""", (context.batch_id,))
        else:
            connection.execute("UPDATE dw.fact_crash SET fatal_crash_eligible=false WHERE batch_id=%s AND source_id='syn_nsw'", (context.batch_id,))
        connection.execute("SET ROLE arsia_loader")
        return original.callback(shared, context)
    request["modules"] = replace(request["modules"], qa_d=replace(original, callback=corrupt))
    failed = run_build(**request).as_dict()
    assert failed["result"] == "failed" and failed["stage"] in {"qa_d", "publish"}, failed
    with connect() as fresh:
        assert current(fresh) == baseline["batch_id"]
        assert batch_rows(fresh, baseline["batch_id"]) == before
        assert all(not rows for rows in batch_rows(fresh, failed["batch_id"]).values())
    assert (Path(failed["evidence_ref"]) / "error.json").is_file()
    record("at06-" + fault, {"baseline": baseline, "failed": failed, "old_batch_unchanged": True})


@pytest.mark.parametrize("variant,code", [
    ("missing_file", "IO_ERROR"), ("bad_header", "HEADER_MISMATCH"), ("bad_hash", "FILE_HASH_MISMATCH"),
])
def test_e07_at02_bad_native_preparation_preserves_real_b0(request_factory, tmp_path, variant, code):
    baseline = run(request_factory())
    with connect() as connection:
        before = batch_rows(connection, baseline["batch_id"])
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("e_s0_variant", root / "tools/create_s0_inputs.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    config = generator.create_s0(tmp_path / variant, variant)
    failed = prepare(config, tmp_path / "rejected-intake")
    assert failed["status"] == "failed" and failed["errors"][0]["code"] == code
    assert "batch_id" not in failed
    with connect() as connection:
        assert current(connection) == baseline["batch_id"]
        assert batch_rows(connection, baseline["batch_id"]) == before
        assert connection.execute("SELECT count(*) FROM meta.batch").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM raw.record").fetchone() == (19,)
    record("at02-" + variant, {"baseline": baseline, "preparation": failed,
          "scope": "Real native admission rejected before a B10 request could be constructed; B0 unchanged"})


def test_e07_at07_forced_invalid_location_rolls_back_real_candidate(request_factory):
    baseline = run(request_factory())
    with connect() as connection:
        before = batch_rows(connection, baseline["batch_id"])
    request = request_factory(analysis={"year_from": 2020, "year_to": 2023})
    connection = psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"])
    connection.execute("SET ROLE arsia_loader")
    request["connect"] = lambda: connection
    original = request["modules"].canonical
    def force_location(shared, context):
        original.callback(shared, context)
        connection.execute("RESET ROLE")
        # V2's conflicting Node remains unlocated; owner access only injects the fault.
        connection.execute("""UPDATE canonical.crash SET map_eligible=true
            WHERE batch_id=%s AND source_id='syn_vic' AND occurrence_year=2021""", (context.batch_id,))
        pytest.fail("The database accepted map eligibility without a valid location")
    request["modules"] = replace(request["modules"], canonical=replace(original, callback=force_location))
    failed = run_build(**request).as_dict()
    assert (failed["result"], failed["stage"], failed["error_code"]) == ("failed", "canonical", "RUN_ERROR"), failed
    assert "CheckViolation" in failed["message"]
    with connect() as fresh:
        assert current(fresh) == baseline["batch_id"]
        assert batch_rows(fresh, baseline["batch_id"]) == before
        assert all(not rows for rows in batch_rows(fresh, failed["batch_id"]).values())
    record("at07-forced-location", {"baseline": baseline, "failed": failed, "old_batch_unchanged": True})
