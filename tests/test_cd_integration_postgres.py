"""Three-source component chain through B's real interfaces and installed code."""
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from arsia_ingest.manifest import FrozenManifest, s0_definitions
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import BuildModules, ModuleConnection, RunEvidence, _bindings, run_build
from cd_support import ROOT, bindings, interface_manifest, inventory
from test_raw_load_postgres import connection
from test_ac_integration_postgres import (
    TABLES, assert_empty_from_new_session, begin, cleanup_committed_test_data,
    counts, persist_b_checks, raw_rows, snapshot,
)

pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Use tools/verify_cd_postgres.py for the private PostgreSQL 16 run",
)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = Path(os.environ.get("CD_EVIDENCE_DIR", tmp_path_factory.mktemp("cd")))
    result = prepare(ROOT / "tests/fixtures/s0/config.json", root / "native-intake")
    assert result["status"] == "prepared" and result["raw_count"] == 19
    return Path(result["run_dir"]), root


@pytest.fixture
def frozen(prepared):
    value = interface_manifest(prepared[0])
    assert type(value) is FrozenManifest
    return value


@pytest.fixture(autouse=True)
def private_database(connection):
    marker = os.environ.get("AC_TEST_RUN")
    assert marker, "Committed tests require the verifier's disposable database"
    assert connection.execute("SELECT current_setting('arsia.test_run',true)").fetchone() == (marker,)
    assert connection.execute("SELECT current_user,session_user").fetchone() == (
        "arsia_loader", "arsia_loader",
    )
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    connection.rollback()


def call(conn, context, stage):
    child = replace(context, evidence=context.evidence.for_stage(stage))
    return bindings()[stage].callback(ModuleConnection(conn), child)


def canonical(conn, context):
    assert call(conn, context, "project") == {"project_source_count": 3}
    projected = {kind: conn.execute(
        f"SELECT * FROM pg_temp.arsia_i_{kind} ORDER BY source_id,{kind}_key"
    ).fetchall() for kind in ("crash", "unit")}
    assert all(len(row) == 24 for row in projected["crash"])
    assert all(len(row) == 11 for row in projected["unit"])
    call(conn, context, "vault")
    call(conn, context, "canonical")
    for kind, expected in projected.items():
        actual = conn.execute(
            f"SELECT * FROM canonical.{kind} WHERE batch_id=%s ORDER BY source_id,{kind}_key",
            (context.batch_id,),
        ).fetchall()
        assert actual == expected
    return projected


def complete(conn, context):
    projected = canonical(conn, context)
    result = call(conn, context, "dw")
    assert result == {"dim_source": 3, "dim_month": 60, "dim_severity": 12, "fact_crash": 6}
    assert call(conn, context, "qa_d") == {
        "qa06_object_count": 15, "qa06_pass_count": 15, "qa06_block_count": 0,
    }
    return projected


def full_snapshot(conn, batch):
    return snapshot(conn, batch) | {"dw.fact_crash": conn.execute(
        "SELECT to_jsonb(t) FROM dw.fact_crash t WHERE batch_id=%s ORDER BY to_jsonb(t)::text",
        (batch,),
    ).fetchall()}


def cleanup(batches, frozen):
    import psycopg
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
        assert admin.execute("SELECT current_setting('arsia.test_run',true)").fetchone() == (
            os.environ["AC_TEST_RUN"],
        )
        admin.execute("DELETE FROM dw.fact_crash WHERE batch_id=ANY(%s::uuid[])", (batches,))
    cleanup_committed_test_data(batches, frozen)


def test_real_b_three_source_chain_exact_definitions_qa_and_caller_rollback(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    before_raw = raw_rows(connection)
    projected = canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (6, 6)
    assert connection.execute("""SELECT source_id,count(*),sum(fatality_count),sum(casualty_count),
        count(*) FILTER(WHERE map_eligible) FROM canonical.crash
        WHERE batch_id=%s GROUP BY source_id ORDER BY source_id""", (context.batch_id,)).fetchall() == [
        ("syn_nsw", 2, 2, 3, 1), ("syn_qld", 2, 0, 1, 2), ("syn_vic", 2, 1, 3, 1),
    ]
    assert connection.execute("""SELECT source_id,count(*) FROM canonical.unit
        WHERE batch_id=%s GROUP BY source_id ORDER BY source_id""", (context.batch_id,)).fetchall() == [
        ("syn_nsw", 3), ("syn_vic", 3),
    ]
    assert call(connection, context, "dw") == {
        "dim_source": 3, "dim_month": 60, "dim_severity": 12, "fact_crash": 6,
    }
    definitions = s0_definitions(ROOT / "tests/fixtures/s0/contract.json")
    actual_sources = connection.execute("""SELECT source_id,source_name,jurisdiction_code,release_label,
        release_scope FROM dw.dim_source WHERE batch_id=%s""", (context.batch_id,)).fetchall()
    assert sorted(actual_sources) == sorted(tuple(row[k] for k in (
        "source_id", "source_name", "jurisdiction_code", "release_label", "release_scope",
    )) for row in definitions["sources"])
    assert connection.execute("SELECT * FROM dw.dim_month ORDER BY month_id").fetchall() == [
        (year * 100 + month, year, month) for year in range(2020, 2025) for month in range(1, 13)
    ]
    actual_severity = connection.execute("""SELECT source_id,severity_code,severity_label,
        definition_version,definition_text FROM dw.dim_severity WHERE batch_id=%s""",
        (context.batch_id,)).fetchall()
    assert sorted(actual_severity) == sorted(tuple(row[k] for k in (
        "source_id", "severity_code", "severity_label", "definition_version", "definition_text",
    )) for row in definitions["severity"])
    assert connection.execute("""SELECT source_id,severity_code,count(*) FROM dw.fact_crash
        WHERE batch_id=%s GROUP BY source_id,severity_code ORDER BY source_id,severity_code""",
        (context.batch_id,)).fetchall() == [
        ("syn_nsw", "F", 1), ("syn_nsw", "__MISSING__", 1), ("syn_qld", "I", 1),
        ("syn_qld", "N", 1), ("syn_vic", "F", 1), ("syn_vic", "I", 1),
    ]
    assert connection.execute("""SELECT month_id,is_fatal_crash,fatality_count,casualty_count,
        fatal_crash_eligible,fatality_eligible,casualty_eligible FROM dw.fact_crash
        WHERE batch_id=%s AND severity_code='__MISSING__'""", (context.batch_id,)).fetchone() == (
        None, None, None, None, False, False, False,
    )
    persist_b_checks(connection, context, prepared)
    assert call(connection, context, "qa_d") == {
        "qa06_object_count": 15, "qa06_pass_count": 15, "qa06_block_count": 0,
    }
    rows = connection.execute("""SELECT object_key,result,affected_count,actual,expected,evidence
        FROM qa.check_result WHERE batch_id=%s AND rule_id='QA06_RECONCILIATION'""",
        (context.batch_id,)).fetchall()
    concrete = [row for row in rows if row[0] != "batch"]
    assert {row[0] for row in concrete} == {
        f"source_year:{source}:{year}" for source in ("syn_nsw", "syn_vic", "syn_qld")
        for year in range(2020, 2025)
    }
    expected_counts = {("syn_nsw", 2020): 2, ("syn_vic", 2020): 1,
                       ("syn_vic", 2021): 1, ("syn_qld", 2020): 1, ("syn_qld", 2021): 1}
    for key, result, affected, actual, expected, evidence in concrete:
        _, source, year = key.split(":")
        assert result == "pass" and affected == 0
        assert actual == expected
        assert actual["evaluated_count"] == expected_counts.get((source, int(year)), 0)
        assert actual["violation_count"] == 0 and not any(actual["metrics"].values())
        assert evidence["references"] and evidence["producer_version"] and not evidence["reason_codes"]
    summary = next(row for row in rows if row[0] == "batch")
    assert summary[3] == summary[4] == {"evaluated_count": 15, "violation_count": 0, "metrics": {
        "object_count": 15, "pass_count": 15, "limited_count": 0, "block_count": 0, "missing_count": 0,
    }}
    assert connection.execute("SELECT count(*) FROM qa.check_result").fetchone() == (32,)
    assert raw_rows(connection) == before_raw
    assert connection.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    assert connection.execute("SELECT status FROM meta.batch").fetchone() == ("running",)
    for stage in ("project", "vault", "canonical", "dw", "qa_d"):
        assert list((context.evidence.directory / stage).glob("*.json"))
    context.evidence.write_json("component-result.json", {
        "scope": "S0 three-source components; partial inventory; no E FP1 or publication",
        "manifest_type": type(frozen).__module__ + "." + type(frozen).__name__,
        "raw_rows": 19, "crashes": 6, "units": 6, "facts": 6,
        "dimensions": [3, 60, 12], "qa01_qa02_rows": 16, "qa06_rows": 16,
        "all_projection_fields_preserved": True,
    })
    assert_empty_from_new_session()
    connection.rollback()
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    assert_empty_from_new_session()


def test_repeat_projection_dw_and_qa_append_only_contract(connection, prepared, frozen):
    import psycopg
    context = begin(connection, prepared, frozen)
    complete(connection, context)
    before = full_snapshot(connection, context.batch_id)
    repeat = replace(context, evidence=RunEvidence(context.evidence.directory / "repeat"))
    assert call(connection, repeat, "project") == {"project_source_count": 3}
    assert call(connection, repeat, "dw")["fact_crash"] == 6
    assert full_snapshot(connection, context.batch_id) == before
    with pytest.raises(IntakeError, match="already contains Canonical"):
        call(connection, repeat, "canonical")
    with connection.transaction():
        with pytest.raises(psycopg.errors.UniqueViolation):
            with connection.transaction():
                call(connection, repeat, "qa_d")
    assert full_snapshot(connection, context.batch_id) == before


def test_analysis_scope_filters_each_source_and_keeps_full_raw(connection, prepared, frozen):
    value = frozen.as_dict()
    value["analysis"] = {"year_from": 2021, "year_to": 2024}
    context = begin(connection, prepared, FrozenManifest(json.dumps(value)))
    before_raw = raw_rows(connection)
    projected = canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (2, 2)
    assert {row[1] for row in projected["crash"]} == {"syn_vic", "syn_qld"}
    assert call(connection, context, "dw") == {
        "dim_source": 3, "dim_month": 48, "dim_severity": 12, "fact_crash": 2,
    }
    assert call(connection, context, "qa_d") == {
        "qa06_object_count": 12, "qa06_pass_count": 12, "qa06_block_count": 0,
    }
    assert raw_rows(connection) == before_raw


@pytest.mark.parametrize("changed_field", ["source_name", "severity_label"])
def test_same_batch_conflicting_definitions_fail_and_rollback(connection, prepared, frozen, changed_field):
    context = begin(connection, prepared, frozen)
    complete(connection, context)
    before = full_snapshot(connection, context.batch_id)
    value = frozen.as_dict()
    row = value["sources"][0] if changed_field == "source_name" else value["rules"]["severity"][0]
    row[changed_field] += " changed"
    changed = replace(context, manifest=FrozenManifest(json.dumps(value)),
                      evidence=RunEvidence(context.evidence.directory / "conflict"))
    with pytest.raises(IntakeError) as error:
        call(connection, changed, "dw")
    assert error.value.code == "D02_DATABASE_MISMATCH"
    assert full_snapshot(connection, context.batch_id) == before
    connection.rollback()
    assert_empty_from_new_session()


def test_new_batch_definitions_and_facts_preserve_committed_history(connection, prepared, frozen):
    batches = []
    try:
        first = begin(connection, prepared, frozen)
        batches.append(first.batch_id)
        complete(connection, first)
        connection.commit()  # Committed component fixture, not a published batch.
        before = full_snapshot(connection, first.batch_id)
        value = frozen.as_dict()
        value["sources"][0]["release_label"] += " next snapshot"
        value["rules"]["severity"][0]["severity_label"] += " next snapshot"
        source = value["sources"][0]
        for contract in value["rules"]["contracts"]:
            if contract["content"]["input"]["source_id"] == source["source_id"]:
                contract["content"]["identity"]["release_label"] = source["release_label"]
        second = begin(connection, prepared, FrozenManifest(json.dumps(value)), previous=first.batch_id)
        batches.append(second.batch_id)
        complete(connection, second)
        assert connection.execute("""SELECT release_label FROM dw.dim_source
            WHERE batch_id=%s AND source_id=%s""", (second.batch_id, source["source_id"])).fetchone() == (
                source["release_label"],
            )
        severity = value["rules"]["severity"][0]
        assert connection.execute("""SELECT severity_label FROM dw.dim_severity
            WHERE batch_id=%s AND source_id=%s AND severity_code=%s""",
            (second.batch_id, severity["source_id"], severity["severity_code"])).fetchone() == (
                severity["severity_label"],
            )
        assert connection.execute("SELECT count(*) FROM dw.fact_crash").fetchone() == (12,)
        assert full_snapshot(connection, first.batch_id) == before
        assert connection.execute("SELECT count(*) FROM dw.dim_month").fetchone() == (60,)
        assert connection.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
        connection.rollback()
        assert full_snapshot(connection, first.batch_id) == before
        assert not any(full_snapshot(connection, second.batch_id).values())
    finally:
        connection.rollback()
        cleanup(batches, frozen)


def test_full_build_still_requires_real_c10_e_and_final_inventory(prepared, frozen):
    def forbidden_connection():
        raise AssertionError("Partial inventory must block before connecting")
    modules = BuildModules(**bindings())
    result = run_build(connect=forbidden_connection, prepared_run=prepared[0], manifest=frozen,
                       project_root=ROOT, inventory=inventory(), modules=modules, fp1=None,
                       evidence_root=prepared[1] / "full-build-preflight")
    assert result.exit_code == 1 and result.as_dict()["error_code"] == "MANIFEST_VERSION_MISSING"
    with pytest.raises(IntakeError) as error:
        _bindings(modules, None, inventory())
    assert error.value.code == "MODULE_UNAVAILABLE"
    assert set(error.value.details["modules"]) == {"qa_c", "publish"}
