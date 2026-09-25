"""PR18 lineage regression checks against D's accepted fix."""
from dataclasses import replace
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from arsia_c.canonical_validation import selected_contracts
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import ModuleConnection
from cd_support import ROOT, bindings, interface_manifest
from d_acceptance_support import connection, fault_injection
from test_ac_integration_postgres import (
    TABLES, assert_empty_from_new_session, begin, counts,
)

pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Run tools/verify_d04_lineage_postgres.py in its private PG16 database",
)
CASES = [("primary", source) for source in ("syn_nsw", "syn_vic", "syn_qld")] + [
    ("direct", "syn_nsw"), ("direct", "syn_qld"), ("node", "syn_vic"),
]


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    parent = Path(os.environ.get("CD_EVIDENCE_DIR", tmp_path_factory.mktemp("lineage")))
    root = parent / "lineage"
    result = prepare(ROOT / "tests/fixtures/s0/config.json", root / "native-intake")
    assert result["status"] == "prepared" and result["raw_count"] == 19
    return Path(result["run_dir"]), root


@pytest.fixture
def frozen(prepared):
    value = interface_manifest(prepared[0])
    assert type(value) is FrozenManifest
    return value


@pytest.fixture(autouse=True)
def isolated(connection):
    marker = os.environ.get("AC_TEST_RUN")
    assert marker
    assert connection.execute("SELECT current_setting('arsia.test_run',true)").fetchone() == (marker,)
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    yield
    connection.rollback()
    assert_empty_from_new_session()


def call(conn, context, stage):
    assert conn.execute("SELECT current_user").fetchone() == ("arsia_loader",)
    child = replace(context, evidence=context.evidence.for_stage(stage))
    return bindings()[stage].callback(ModuleConnection(conn), child)


def load(conn, prepared, frozen, *, canonical=True):
    context = begin(conn, prepared, frozen)
    assert call(conn, context, "project") == {"project_source_count": 3}
    call(conn, context, "vault")
    if canonical:
        call(conn, context, "canonical")
        assert call(conn, context, "dw") == {
            "dim_source": 3, "dim_month": 60, "dim_severity": 12, "fact_crash": 6,
        }
    return context


def raw(conn, identifier):
    value = conn.execute("SELECT to_jsonb(r) FROM raw.record r WHERE raw_record_id=%s",
                         (identifier,)).fetchone()
    assert value is not None
    return value[0]


def encoded(conn, payload, fields):
    return conn.execute("SELECT rv.encode_business_key(VARIADIC %s::text[])",
                        ([payload[field] for field in fields],)).fetchone()[0]


def select_fault(conn, context, kind, source):
    target = conn.execute("""SELECT to_jsonb(c) FROM pg_temp.arsia_i_crash c
        WHERE source_id=%s AND map_eligible ORDER BY crash_key LIMIT 1""", (source,)).fetchone()[0]
    old_id = target["raw_record_id" if kind == "primary" else "location_record_id"]
    original = raw(conn, old_id)
    primary = raw(conn, target["raw_record_id"])
    spec = next(f for f in selected_contracts(context.manifest.as_dict())
                if f["source_id"] == source and f["resource_id"] == original["resource_id"])
    choices = conn.execute("""SELECT to_jsonb(r) FROM raw.record r
        WHERE source_id=%s AND resource_id=%s AND file_sha256=%s AND parser_version=%s
          AND raw_record_id<>%s ORDER BY row_locator::text""",
        (source, original["resource_id"], original["file_sha256"],
         original["parser_version"], old_id)).fetchall()
    if kind == "node":
        assert spec["parent_resource_id"] == primary["resource_id"]
        parent = encoded(conn, primary["payload"], spec["parent_crash_fields"])
        wrong = next(r[0] for r in choices
                     if encoded(conn, r[0]["payload"], spec["parent_fields"]) != parent)
        observed = encoded(conn, wrong["payload"], spec["parent_fields"])
    else:
        assert encoded(conn, primary["payload"], spec["key_fields"]) == target["crash_key"]
        wrong = next(r[0] for r in choices
                     if encoded(conn, r[0]["payload"], spec["key_fields"]) != target["crash_key"])
        parent = target["crash_key"]
        observed = encoded(conn, wrong["payload"], spec["key_fields"])
        if kind == "direct":
            assert old_id == target["raw_record_id"]
    assert parent != observed
    assert all(original[k] == wrong[k] for k in (
        "source_id", "resource_id", "file_sha256", "parser_version",
    ))
    return target, wrong, {
        "kind": kind, "source_id": source, "crash_key": target["crash_key"],
        "original_raw": original, "replacement_raw": wrong,
        "expected_key_or_parent": parent, "replacement_key_or_parent": observed,
        "same_frozen_file": True,
    }


def inject(conn, context, target, wrong, kind, *, satellite=False):
    from psycopg.types.json import Jsonb

    with fault_injection(conn):
        if satellite:
            if kind == "primary":
                statement = "UPDATE rv.sat_crash SET raw_record_id=%s"
                value = wrong["raw_record_id"]
            else:
                statement = "UPDATE rv.sat_crash SET attributes=jsonb_set(attributes,'{location_record_id}',%s)"
                value = Jsonb(wrong["raw_record_id"])
        else:
            column = "raw_record_id" if kind == "primary" else "location_record_id"
            statement = "UPDATE canonical.crash SET " + column + "=%s"
            value = wrong["raw_record_id"]
        result = conn.execute(statement + " WHERE batch_id=%s AND source_id=%s AND crash_key=%s",
                              (value, context.batch_id, target["source_id"], target["crash_key"]))
        assert result.rowcount == 1
        conn.execute("SET CONSTRAINTS ALL IMMEDIATE")


def facts(conn):
    return conn.execute("SELECT to_jsonb(f) FROM dw.fact_crash f ORDER BY source_id,crash_key").fetchall()


def qa(conn, context):
    returned = call(conn, context, "qa_d")
    rows = conn.execute("""SELECT to_jsonb(q) FROM qa.check_result q
        WHERE batch_id=%s AND rule_id='QA06_RECONCILIATION' ORDER BY object_key""",
        (context.batch_id,)).fetchall()
    results = {row[0]["object_key"]: row[0] for row in rows}
    assert len(results) == 16
    summary = json.loads((context.evidence.directory / "qa_d/d04-qa06-summary.json").read_text(encoding="utf-8"))
    assert summary == {"batch_id": context.batch_id, **returned}
    assert conn.execute("SELECT status FROM meta.batch WHERE batch_id=%s", (context.batch_id,)).fetchone() == ("running",)
    assert conn.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    assert_empty_from_new_session()
    return returned, results


def blocked(row, summary, context, *, metric, target=None):
    assert row["result"] == summary["result"] == "block"
    assert row["affected_count"] == summary["affected_count"] == 1
    assert row["actual"]["metrics"][metric] == 1
    details = [r for r in row["evidence"]["references"] if "path" in r]
    assert len(details) == 1 and details[0]["row_count"] == 1
    path = Path(details[0]["path"])
    assert path.is_relative_to(context.evidence.directory)
    import hashlib
    assert hashlib.sha256(path.read_bytes()).hexdigest() == details[0]["sha256"]
    detail = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(detail) == 1
    reason = "LINEAGE_ERROR" if metric == "lineage_error_count" else "FIELD_MISMATCH"
    assert reason in detail[0]["issues"]
    assert reason in row["evidence"]["reason_codes"]
    if target is not None:
        assert detail[0]["source_id"] == target["source_id"]
        assert detail[0]["crash_key"] == target["crash_key"]


@pytest.mark.parametrize("kind,source", CASES)
def test_wrong_row_lineage(connection, prepared, frozen, kind, source):
    context = load(connection, prepared, frozen)
    before = facts(connection)
    target, wrong, evidence = select_fault(connection, context, kind, source)
    inject(connection, context, target, wrong, kind)
    assert facts(connection) == before
    returned, rows = qa(connection, context)
    key = f"source_year:{source}:{target['occurrence_year']}"
    row, summary = rows[key], rows["batch"]
    context.evidence.write_json("lineage-case.json", {
        **evidence, "injected_by": "test owner after normal C09 and D03",
        "application_role": "arsia_loader", "facts_unchanged": True,
        "mode": "fix-acceptance", "expected_result": "block",
        "callback_counts": returned, "actual_object": row, "actual_batch": summary,
        "all_qa_results": rows,
    })
    blocked(row, summary, context, metric="lineage_error_count", target=target)
    assert returned == {"qa06_object_count": 15, "qa06_pass_count": 14, "qa06_block_count": 1}
    assert not any(value for name, value in row["actual"]["metrics"].items()
                   if name != "lineage_error_count")


@pytest.mark.parametrize("kind,source", CASES)
def test_c09_rejects_same_fault_before_canonical(connection, prepared, frozen, kind, source):
    context = load(connection, prepared, frozen, canonical=False)
    target, wrong, evidence = select_fault(connection, context, kind, source)
    inject(connection, context, target, wrong, kind, satellite=True)
    with pytest.raises(IntakeError) as error:
        call(connection, context, "canonical")
    assert error.value.code == "CANONICAL_CONTRACT"
    expected = "Satellite identity" if kind == "primary" else "exact Node"
    assert expected in str(error.value)
    assert connection.execute("SELECT count(*) FROM canonical.crash").fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM dw.fact_crash").fetchone() == (0,)
    context.evidence.write_json("c09-control.json", {
        **evidence, "injected_by": "test owner into Satellite before C09",
        "error_code": error.value.code, "message": str(error.value), "canonical_rows": 0,
    })


def test_baseline_and_rollback(connection, prepared, frozen):
    context = load(connection, prepared, frozen)
    returned, rows = qa(connection, context)
    assert returned["qa06_pass_count"] == 15
    assert all(r["result"] == "pass" for r in rows.values())
    connection.rollback()
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    assert_empty_from_new_session()


def test_wrong_file_is_already_blocked(connection, prepared, frozen):
    context = load(connection, prepared, frozen)
    target, _, _ = select_fault(connection, context, "primary", "syn_nsw")
    identifier = connection.execute("""SELECT raw_record_id FROM raw.record
        WHERE source_id='syn_nsw' AND resource_id='syn_nsw_traffic_unit' LIMIT 1""").fetchone()[0]
    wrong = raw(connection, identifier)
    inject(connection, context, target, wrong, "primary")
    _, rows = qa(connection, context)
    blocked(rows["source_year:syn_nsw:2020"], rows["batch"], context, metric="lineage_error_count")


def test_fact_change_is_already_blocked(connection, prepared, frozen):
    context = load(connection, prepared, frozen)
    with fault_injection(connection):
        assert connection.execute("""UPDATE dw.fact_crash SET latitude=latitude+0.01
            WHERE batch_id=%s AND source_id='syn_nsw' AND map_eligible""",
            (context.batch_id,)).rowcount == 1
    _, rows = qa(connection, context)
    blocked(rows["source_year:syn_nsw:2020"], rows["batch"], context, metric="field_mismatch_count")


def test_loader_permissions_and_foreign_keys_still_hold(connection, prepared, frozen):
    import psycopg

    context = load(connection, prepared, frozen)
    statement = "UPDATE canonical.crash SET raw_record_id=%s WHERE batch_id=%s AND source_id='syn_nsw'"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with connection.transaction():
            connection.execute(statement, (str(uuid4()), context.batch_id))
    with fault_injection(connection):
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with connection.transaction():
                connection.execute(statement, (str(uuid4()), context.batch_id))
        other_source = connection.execute("SELECT raw_record_id FROM raw.record WHERE source_id='syn_qld' LIMIT 1").fetchone()[0]
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with connection.transaction():
                connection.execute(statement, (other_source, context.batch_id))
    assert qa(connection, context)[0]["qa06_pass_count"] == 15
