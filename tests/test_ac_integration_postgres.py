"""Installed B/A/C modules on one real loader session, with partial inventory."""
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.qa_input import check_inputs, check_raw, write_results
from arsia_ingest.raw_load import load_prepared
from arsia_ingest.runner import (
    BuildModules, ModuleConnection, RunContext, RunEvidence, _bindings, run_build,
)
from ac_support import ROOT, bindings, interface_manifest, inventory
from test_raw_load_postgres import connection

pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Use tools/verify_ac_postgres.py for a private PostgreSQL 16 database",
)

TABLES = (
    "meta.source", "meta.resource", "raw.record", "meta.batch",
    "rv.hub_crash", "rv.hub_unit", "rv.sat_crash", "rv.sat_unit", "rv.link_crash_unit",
    "canonical.crash", "canonical.unit", "dw.dim_source", "dw.dim_month",
    "dw.dim_severity", "dw.fact_crash", "qa.check_result", "meta.current_release",
)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = Path(os.environ.get("AC_EVIDENCE_DIR", tmp_path_factory.mktemp("ac")))
    result = prepare(ROOT / "tests/fixtures/s0/config.json", root / "native-intake")
    assert result["status"] == "prepared" and result["raw_count"] == 19
    return Path(result["run_dir"]), root


@pytest.fixture
def frozen(prepared):
    value = interface_manifest(prepared[0])
    assert type(value) is FrozenManifest
    return value


def counts(conn):
    return {table: conn.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in TABLES}


@pytest.fixture(autouse=True)
def private_database(connection):
    marker = os.environ.get("AC_TEST_RUN")
    assert marker, "Use tools/verify_ac_postgres.py; these tests require its disposable database"
    assert connection.execute("SELECT current_setting('arsia.test_run',true)").fetchone() == (marker,)
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    connection.rollback()


def raw_rows(conn):
    return conn.execute("SELECT * FROM raw.record ORDER BY raw_record_id").fetchall()


def snapshot(conn, batch):
    tables = ("rv.sat_crash", "rv.sat_unit", "rv.link_crash_unit", "canonical.crash",
              "canonical.unit", "dw.dim_source", "dw.dim_severity", "qa.check_result")
    return {table: conn.execute(
        f"SELECT to_jsonb(t) FROM {table} t WHERE batch_id=%s ORDER BY to_jsonb(t)::text", (batch,),
    ).fetchall() for table in tables}


def begin(conn, prepared, manifest, *, previous=None):
    from psycopg.types.json import Jsonb

    loaded = load_prepared(conn, prepared[0], manifest.as_dict()["sources"])
    assert loaded.raw_count == 19
    batch = str(uuid4())
    # This is a test batch identifier, not an E03 FP1 result.
    identifier = hashlib.sha256(("B/A/C component test " + batch).encode()).hexdigest()
    conn.execute("""INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest)
        VALUES (%s,'synthetic',%s,%s)""", (batch, identifier, Jsonb(manifest.as_dict())))
    return RunContext(str(uuid4()), "synthetic", batch, identifier, previous, manifest,
                      RunEvidence(prepared[1] / "runs" / batch))


def call(conn, context, stage):
    binding = bindings()[stage]
    child = replace(context, evidence=context.evidence.for_stage(stage))
    return binding.callback(ModuleConnection(conn), child)


def through_canonical(conn, context):
    call(conn, context, "project")
    before = {kind: conn.execute(
        f"SELECT * FROM pg_temp.arsia_i_{kind} ORDER BY {kind}_key"
    ).fetchall() for kind in ("crash", "unit")}
    assert all(len(row) == 24 for row in before["crash"])
    assert all(len(row) == 11 for row in before["unit"])
    call(conn, context, "vault")
    call(conn, context, "canonical")
    for kind, expected in before.items():
        actual = conn.execute(
            f"SELECT * FROM canonical.{kind} WHERE batch_id=%s ORDER BY {kind}_key", (context.batch_id,),
        ).fetchall()
        assert actual == expected
    return before


def persist_b_checks(conn, context, prepared):
    manifest = context.manifest.as_dict()
    evidence = context.evidence.directory / "input"
    reports = [
        check_inputs(manifest, prepared[0].parents[2], evidence_dir=evidence / "qa01",
                     producer_version="b-ac-integration-v1", supported_mappings=manifest["rules"]["mappings"]),
        check_raw(ModuleConnection(conn), manifest, prepared[0].parents[2], evidence_dir=evidence / "qa02",
                  producer_version="b-ac-integration-v1"),
    ]
    for report in reports:
        assert not report.blocked and len(report.rows) == 8
        write_results(ModuleConnection(conn), context.batch_id, report)
    actual = conn.execute("""SELECT rule_id,object_key,result,affected_count,actual,expected,evidence,
        raw_record_id,checked_at FROM qa.check_result WHERE batch_id=%s ORDER BY rule_id,object_key""",
        (context.batch_id,)).fetchall()
    expected = sorted([row for report in reports for row in report.rows], key=lambda r: (r["rule_id"], r["object_key"]))
    from datetime import datetime
    for row, original in zip(actual, expected, strict=True):
        assert row[:8] == tuple(original[k] for k in (
            "rule_id", "object_key", "result", "affected_count", "actual", "expected", "evidence", "raw_record_id"))
        assert row[8] == datetime.fromisoformat(original["checked_at"])
    assert len(actual) == 16


def assert_empty_from_new_session():
    import psycopg
    with psycopg.connect(os.environ["ARSIA_TEST_DSN"]) as observer:
        assert counts(observer) == dict.fromkeys(TABLES, 0)


def test_real_b_objects_nsw_chain_qa_persistence_and_caller_rollback(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    before_raw = raw_rows(connection)
    projected = through_canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (2, 3)
    first, missing = projected["crash"]
    assert first[3] == '["0001"]'
    assert first[5:23] == (
        2020, 1, None, "month", "F", "F", "syn-1", True, 2, 3, True, True, True,
        Decimal("-33.8600000"), Decimal("151.2000000"), "EPSG:4326", True, first[4],
    )
    assert first[23] == {}
    assert missing[3] == '["0002"]'
    assert missing[5:23] == (
        2020, None, None, "year", None, "__MISSING__", "syn-1", None, None, None,
        False, False, False, None, None, None, False, None,
    )
    assert {r["field"] for r in missing[23]["fields"]} == {"fatal_crash_eligible", "fatality_count", "casualty_count"}
    assert all(r["reason_code"] == "missing" for r in missing[23]["fields"])
    assert missing[23]["location"]["reason_code"] == "missing"
    assert [row[3:5] for row in projected["unit"]] == [
        ('["0001", "01"]', '["0001"]'), ('["0001", "02"]', '["0001"]'),
        ('["0002", "01"]', '["0002"]'),
    ]
    assert all(row[7:10] == ("CAR", "synthetic_traffic_unit", True) for row in projected["unit"])
    assert call(connection, context, "dw") == {"dim_source": 3, "dim_month": 60, "dim_severity": 12}
    persist_b_checks(connection, context, prepared)
    assert raw_rows(connection) == before_raw
    assert connection.execute("SELECT count(*) FROM canonical.crash WHERE source_id<>'syn_nsw'").fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    assert_empty_from_new_session()
    files = {stage: [p.name for p in (context.evidence.directory / stage).glob("*.json")]
             for stage in ("project", "vault", "canonical", "dw")}
    assert all(files.values())
    canonical_evidence = json.loads((context.evidence.directory / "canonical/c09-canonical-counts.json").read_text())
    assert canonical_evidence["satellite_reconciled"] is True
    context.evidence.write_json("integration-result.json", {
        "scope": "NSW projection/Canonical; three-source Raw and D02; no full build or publication",
        "manifest_type": type(frozen).__module__ + "." + type(frozen).__name__,
        "raw_rows": 19, "crashes": 2, "units": 3, "map_eligible": 1, "qa01_qa02_rows": 16,
        "all_24_11_fields_equal": True, "stage_files": files,
    })
    connection.rollback()
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    assert_empty_from_new_session()


def test_repeated_projection_dimensions_and_canonical_retry_rule(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    through_canonical(connection, context)
    call(connection, context, "dw")
    before = snapshot(connection, context.batch_id)
    repeat = replace(context, evidence=RunEvidence(context.evidence.directory / "repeat"))
    call(connection, repeat, "project")
    call(connection, repeat, "dw")
    assert snapshot(connection, context.batch_id) == before
    with pytest.raises(IntakeError, match="already contains Canonical"):
        call(connection, repeat, "canonical")
    assert not (repeat.evidence.directory / "canonical/c09-canonical-counts.json").exists()
    assert snapshot(connection, context.batch_id) == before


def test_manifest_years_change_projection_and_dimensions_without_changing_raw(connection, prepared, frozen):
    value = frozen.as_dict()
    value["analysis"] = {"year_from": 2021, "year_to": 2024}
    changed = FrozenManifest(json.dumps(value))
    context = begin(connection, prepared, changed)
    before = raw_rows(connection)
    assert through_canonical(connection, context) == {"crash": [], "unit": []}
    assert call(connection, context, "dw") == {"dim_source": 3, "dim_month": 48, "dim_severity": 12}
    assert raw_rows(connection) == before


def dimension_conflict(conn, context):
    call(conn, context, "dw")
    value = context.manifest.as_dict()
    value["sources"][0]["source_name"] += " conflicting definition"
    changed = replace(context, manifest=FrozenManifest(json.dumps(value)),
                      evidence=RunEvidence(context.evidence.directory / "conflict"))
    with pytest.raises(IntakeError) as error:
        call(conn, changed, "dw")
    assert error.value.code == "D02_DATABASE_MISMATCH"
    assert not (changed.evidence.directory / "dw/d02-dimensions.json").exists()


def test_downstream_failure_rolls_back_vault_canonical_dimensions_and_qa(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    through_canonical(connection, context)
    persist_b_checks(connection, context, prepared)
    dimension_conflict(connection, context)
    assert_empty_from_new_session()
    connection.rollback()
    assert counts(connection) == dict.fromkeys(TABLES, 0)


def cleanup_committed_test_data(batches, frozen):
    import psycopg
    value = frozen.as_dict()
    # Only this private test database uses the owner for cleanup.
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
        marker = os.environ.get("AC_TEST_RUN")
        assert marker and admin.execute("SELECT current_setting('arsia.test_run',true)").fetchone() == (marker,)
        for table in ("qa.check_result", "canonical.unit", "canonical.crash", "dw.dim_severity",
                      "dw.dim_source", "rv.link_crash_unit", "rv.sat_unit", "rv.sat_crash"):
            admin.execute(f"DELETE FROM {table} WHERE batch_id=ANY(%s::uuid[])", (batches,))
        for kind in ("unit", "crash"):
            admin.execute(f"DELETE FROM rv.hub_{kind} WHERE first_seen_batch_id=ANY(%s::uuid[])", (batches,))
        admin.execute("DELETE FROM meta.batch WHERE batch_id=ANY(%s::uuid[])", (batches,))
        resources = [f["resource_id"] for f in value["files"]]
        admin.execute("DELETE FROM raw.record WHERE resource_id=ANY(%s)", (resources,))
        admin.execute("DELETE FROM meta.resource WHERE resource_id=ANY(%s)", (resources,))
        admin.execute("DELETE FROM meta.source WHERE source_id=ANY(%s)", ([s["source_id"] for s in value["sources"]],))
        analysis = value["analysis"]
        admin.execute("DELETE FROM dw.dim_month WHERE calendar_year BETWEEN %s AND %s",
                      (analysis["year_from"], analysis["year_to"]))


@pytest.mark.parametrize("outcome", ["new_snapshot", "dimension_conflict"])
def test_next_batch_preserves_committed_test_snapshot(connection, prepared, frozen, outcome):
    batches = []
    try:
        first = begin(connection, prepared, frozen)
        batches.append(first.batch_id)
        through_canonical(connection, first)
        call(connection, first, "dw")
        persist_b_checks(connection, first, prepared)
        connection.commit()  # A test snapshot; no successful release is declared.
        old = snapshot(connection, first.batch_id)
        old_raw = raw_rows(connection)
        second = begin(connection, prepared, frozen, previous=first.batch_id)
        batches.append(second.batch_id)
        through_canonical(connection, second)
        if outcome == "dimension_conflict":
            dimension_conflict(connection, second)
        else:
            call(connection, second, "dw")
            assert connection.execute("SELECT count(*) FROM canonical.crash").fetchone() == (4,)
            assert connection.execute("SELECT count(*) FROM canonical.unit").fetchone() == (6,)
            assert connection.execute("SELECT count(*) FROM dw.dim_source").fetchone() == (6,)
            for kind in ("crash", "unit"):
                assert {str(row[0]) for row in connection.execute(
                    f"SELECT first_seen_batch_id FROM rv.hub_{kind}")} == {first.batch_id}
        assert snapshot(connection, first.batch_id) == old
        assert raw_rows(connection) == old_raw
        connection.rollback()
        assert snapshot(connection, first.batch_id) == old
        assert all(not rows for rows in snapshot(connection, second.batch_id).values())
        assert connection.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    finally:
        connection.rollback()
        cleanup_committed_test_data(batches, frozen)


def test_real_b10_still_blocks_partial_inventory(prepared, frozen):
    import psycopg
    connections = []
    def connect():
        connections.append(True)
        return psycopg.connect(os.environ["ARSIA_TEST_DSN"])
    modules = BuildModules(**bindings())
    result = run_build(connect=connect, prepared_run=prepared[0], manifest=frozen,
                       project_root=ROOT, inventory=inventory(), modules=modules, fp1=None,
                       evidence_root=prepared[1] / "full-build-preflight")
    assert result.exit_code == 1 and result.as_dict()["error_code"] == "MANIFEST_VERSION_MISSING"
    assert not connections
    with pytest.raises(IntakeError) as error:
        _bindings(modules, None, inventory())
    assert error.value.code == "MODULE_UNAVAILABLE"
    assert set(error.value.details["modules"]) == {"qa_c", "qa_d", "publish"}
