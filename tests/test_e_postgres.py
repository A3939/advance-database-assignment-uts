"""E fixes against real B/C/D producers, installed outside the source tree."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

if "AC_TEST_RUN" not in os.environ:
    pytest.skip("Run tools/verify_e_postgres.py for the pinned component assembly", allow_module_level=True)

import psycopg
from psycopg.types.json import Jsonb
from arsia_ingest.fingerprint import FP1Operation, fingerprint
from arsia_ingest.manifest import FrozenManifest, REQUIRED_CHECKS
from arsia_ingest.models import IntakeError
from arsia_ingest.publication import publish, validate_publication_gate
from arsia_ingest.raw_load import load_prepared
from arsia_ingest.runner import ModuleBinding, ModuleConnection, RunContext, RunEvidence
from cd_support import ROOT
from test_raw_load_postgres import connection
from test_cd_integration_postgres import prepared, frozen, private_database, call
from test_ac_integration_postgres import counts, assert_empty_from_new_session
from test_qa_joint_postgres import input_check, finish

OPERATION = FP1Operation("e", "fp1", "e03-fp1-v1.1", 160015, "sql/e/fp1.sql")


@pytest.fixture(scope="session", autouse=True)
def deployment():
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
        assert admin.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ["AC_TEST_RUN"],)
        admin.execute((ROOT / OPERATION.code_path).read_text(encoding="utf-8"))
    yield


def start(conn, prepared, frozen):
    assert isinstance(frozen, FrozenManifest)
    evidence = RunEvidence(prepared[1] / "e-runs" / uuid4().hex)
    inputs = input_check(prepared, frozen, evidence)
    assert not inputs.blocked
    fp = fingerprint(ModuleConnection(conn), frozen, OPERATION, project_root=ROOT)
    assert load_prepared(ModuleConnection(conn), prepared[0], frozen.as_dict()["sources"]).raw_count == 19
    batch = str(uuid4())
    conn.execute("""INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest)
        VALUES (%s,'synthetic',%s,%s)""", (batch, fp, Jsonb(frozen.as_dict())))
    context = RunContext(str(uuid4()), "synthetic", batch, fp, None, frozen, evidence)
    for stage in ("project", "vault", "canonical", "dw"):
        call(conn, context, stage)
    finish(conn, prepared, context, inputs)
    return context


def published(conn, context):
    binding = ModuleBinding(publish, "src/arsia_ingest/publication.py", "e06-publication-v1.1")
    result = binding.callback(ModuleConnection(conn), context)
    assert set(result["qa_summary"]) == set(REQUIRED_CHECKS)
    assert conn.execute("SELECT status FROM meta.batch WHERE batch_id=%s", (context.batch_id,)).fetchone() == ("succeeded",)
    assert str(conn.execute("SELECT batch_id FROM meta.current_release WHERE dataset_kind='synthetic'").fetchone()[0]) == context.batch_id
    context.evidence.write_json("e06-test-result.json", {
        "scope": "Private S0 component release; rolled back, not an official publication",
        "fp1": context.input_fingerprint, "result": result,
    })
    return result


@pytest.mark.parametrize("year_from,limited", [(2020, 2), (2021, 1), (2022, 0)])
def test_real_producers_fp1_publish_and_caller_rollback(connection, prepared, frozen, year_from, limited):
    value = frozen.as_dict()
    value["analysis"]["year_from"] = year_from
    context = start(connection, prepared, FrozenManifest(json.dumps(value)))
    result = published(connection, context)
    assert result["qa_summary"]["QA07_LOCATION"]["affected_count"] == limited
    assert_empty_from_new_session()
    connection.rollback()
    assert not any(counts(connection).values())
    assert_empty_from_new_session()


def test_fp1_pg16_utf8_canonical_json_and_b_normalization(connection, frozen):
    actual = fingerprint(ModuleConnection(connection), frozen, OPERATION, project_root=ROOT)
    canonical = connection.execute("SELECT %s::jsonb::text", (Jsonb(frozen.fingerprint_input()),)).fetchone()[0]
    assert actual == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    original = frozen.as_dict()
    original["provenance"]["prepared_by"] = "Different operator 中文"
    assert fingerprint(ModuleConnection(connection), FrozenManifest(json.dumps(original)), OPERATION, project_root=ROOT) == actual
    original["analysis"]["year_from"] = 2021
    assert fingerprint(ModuleConnection(connection), FrozenManifest(json.dumps(original)), OPERATION, project_root=ROOT) != actual
    values = connection.execute("""SELECT e.fp1('{"z":"中文", "a":1}'::jsonb),
        e.fp1('{"a":1,"z":"中文"}'::jsonb), e.fp1(NULL::jsonb)""").fetchone()
    assert values[0] == values[1] and values[2] is None
    with pytest.raises(IntakeError) as error:
        fingerprint(ModuleConnection(connection), frozen, replace(OPERATION, postgres_version_num=160000), project_root=ROOT)
    assert error.value.code == "FP1_ENVIRONMENT"
    wrong = frozen.as_dict()
    next(f for f in wrong["rules"]["code_files"] if f["path"] == OPERATION.code_path)["sha256"] = "0" * 64
    with pytest.raises(IntakeError) as error:
        fingerprint(ModuleConnection(connection), FrozenManifest(json.dumps(wrong)), OPERATION, project_root=ROOT)

    assert error.value.code == "FP1_CODE"

def test_fp1_only_grants_loader_usage_and_execute(connection):
    assert connection.execute("""SELECT has_schema_privilege('arsia_loader','e','USAGE'),
        has_schema_privilege('arsia_loader','e','CREATE'),
        has_function_privilege('arsia_loader','e.fp1(jsonb)','EXECUTE'),
        has_function_privilege('arsia_reader','e.fp1(jsonb)','EXECUTE')""").fetchone() == (True, False, True, False)
    with connection.transaction():
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction():
                connection.execute("CREATE TABLE e.loader_must_not_create(id integer)")
    assert connection.execute("SELECT current_user,session_user").fetchone() == ("arsia_loader", "arsia_loader")
    assert connection.execute("SELECT e.fp1('{}')").fetchone()[0]


CASES = [
    "coverage", "metrics", "evidence", "summary", "extra_block", "missing_object",
    "missing_summary", "required_block", "invented_expectation", "boolean_metric", "metric_keys",
    "null_skip", "null_without_reason", "summary_affected", "summary_expected", "nonqa07_limited",
    "limited_affected", "limited_reasons", "evidence_hash", "evidence_file", "evidence_count",
    "limited_detail_count", "zero_coverage", "extra_object", "extra_pass_rule", "wrong_file",
    "violation", "expected_violation", "negative_coverage", "forged_zero_expected",
    "meaningless_evidence", "boolean_coverage", "wrong_batch_evidence",
    "other_file_reference", "other_resource_reference", "other_source_reference",
    "other_year_reference", "other_object_reference", "source_without_year",
    "other_summary_object", "missing_summary_reference", "other_detail_object", "other_summary_document",
]


def mutate(conn, batch, case):
    rows = [r[0] for r in conn.execute("SELECT to_jsonb(q) FROM qa.check_result q WHERE batch_id=%s", (batch,))]
    def pick(rule, key=None):
        return next(r for r in rows if r["rule_id"].startswith(rule) and
                    (r["object_key"] == key if key else r["object_key"] != "batch"))
    row = pick("QA02")
    if case == "coverage": row["actual"]["evaluated_count"] = 0
    elif case == "metrics":
        row = pick("QA01"); row["actual"]["metrics"]["hash_match"] = False
    elif case == "evidence": row["evidence"] = {}
    elif case in {"summary", "summary_affected", "summary_expected"}:
        row = pick("QA07", "batch")
        if case == "summary":
            row["result"] = "pass"; row["actual"]["metrics"].update(limited_count=0, pass_count=15)
        elif case == "summary_affected": row["affected_count"] = 0
        else: row["expected"]["metrics"]["limited_count"] = 0
    elif case in {"extra_block", "extra_pass_rule", "extra_object"}:
        conn.execute("""INSERT INTO qa.check_result(batch_id,rule_id,object_key,result,affected_count,actual,expected,evidence)
            VALUES (%s,%s,%s,%s,0,%s,%s,%s)""", (batch,
                "QA02_RAW" if case == "extra_object" else "QA08_DIAGNOSTIC", "extra",
                "block" if case == "extra_block" else "pass", Jsonb(row["actual"]), Jsonb(row["expected"]), Jsonb(row["evidence"])))
        return
    elif case in {"missing_object", "missing_summary"}:
        if case == "missing_summary": row = pick("QA02", "batch")
        conn.execute("DELETE FROM qa.check_result WHERE batch_id=%s AND rule_id=%s AND object_key=%s", (batch, row["rule_id"], row["object_key"])); return
    elif case == "required_block": row["result"] = "block"
    elif case == "invented_expectation":
        row = pick("QA01"); row["actual"]["metrics"]["hash_match"] = row["expected"]["metrics"]["hash_match"] = False
    elif case == "boolean_metric":
        row = pick("QA01"); row["actual"]["metrics"]["hash_match"] = 1
    elif case == "metric_keys": row["actual"]["metrics"].pop("payload_mismatch_count")
    elif case == "null_skip": row["expected"]["metrics"]["payload_mismatch_count"] = None
    elif case == "null_without_reason":
        row = pick("QA04"); row["evidence"]["references"] = [r for r in row["evidence"]["references"] if "null_metric_reasons" not in r]
    elif case == "nonqa07_limited": row["result"] = "limited"
    elif case in {"limited_affected", "limited_reasons", "limited_detail_count"}:
        row = next(r for r in rows if r["rule_id"] == "QA07_LOCATION" and r["object_key"] != "batch" and r["result"] == "limited")
        if case == "limited_affected": row["affected_count"] = 0
        elif case == "limited_reasons": row["evidence"]["reason_codes"] = []
        else: next(r for r in row["evidence"]["references"] if "detail_row_count" in r)["detail_row_count"] += 1
    elif case in {"evidence_hash", "evidence_file", "evidence_count"}:
        ref = row["evidence"]["references"][0]["detail"]
        if case == "evidence_hash": ref["sha256"] = "0"*64
        elif case == "evidence_file": ref["path"] += ".missing"
        else: ref["row_count"] += 1
    elif case == "zero_coverage":
        row = next(r for r in rows if r["rule_id"] == "QA07_LOCATION" and not r["actual"]["evaluated_count"])
        next(r for r in row["evidence"]["references"] if "coverage" in r)["coverage"] = 1.0
    elif case == "meaningless_evidence": row["evidence"]["references"] = [{"unrelated": "text"}]
    elif case == "boolean_coverage":
        row = next(r for r in rows if r["rule_id"] == "QA07_LOCATION" and r["object_key"] != "batch" and r["actual"]["metrics"]["map_count"] > 0)
        next(r for r in row["evidence"]["references"] if "coverage" in r)["coverage"] = True
    elif case == "wrong_batch_evidence":
        row = pick("QA06"); row["evidence"]["references"][0]["batch_id"] = str(uuid4())
    elif case in {"other_file_reference", "other_resource_reference", "other_source_reference"}:
        prefix = {"other_file_reference": "QA01", "other_resource_reference": "QA03", "other_source_reference": "QA05"}[case]
        row = pick(prefix)
        other = next(r for r in rows if r["rule_id"] == row["rule_id"] and r["object_key"] not in {"batch", row["object_key"]})
        row["evidence"]["references"] = other["evidence"]["references"]
        if case == "other_resource_reference":
            row["evidence"]["references"] = [ref for ref in row["evidence"]["references"]
                                            if ref.get("resource_id") != row["object_key"].removeprefix("resource:")]
    elif case in {"other_year_reference", "source_without_year"}:
        row = pick("QA06")
        if case == "other_year_reference": row["evidence"]["references"][0]["occurrence_year"] += 1
        else: row["evidence"]["references"][0].pop("occurrence_year")
    elif case == "other_object_reference":
        row["evidence"]["references"].append({"object_key": pick("QA06")["object_key"]})
    elif case in {"other_summary_object", "missing_summary_reference"}:
        row = pick("QA06", "batch")
        if case == "other_summary_object": row["evidence"]["references"][0]["object_key"] = "source_year:syn_nsw:9999"
        else: row["evidence"]["references"].pop()
    elif case == "other_detail_object":
        row = pick("QA04")
        detail = next(ref for r in rows if r["rule_id"] == "QA07_LOCATION" and r["object_key"] != "batch"
                      for ref in r["evidence"]["references"] if "detail_row_count" in ref)
        row["evidence"]["references"].append(detail)
    elif case == "other_summary_document":
        row = pick("QA03", "batch")
        row["evidence"]["references"] = pick("QA01")["evidence"]["references"]
    elif case == "wrong_file": row["evidence"]["references"][0]["file_sha256"] = "0"*64
    elif case == "violation": row["actual"]["violation_count"] = 1
    elif case == "expected_violation": row["expected"]["violation_count"] = 1
    elif case == "negative_coverage": row["actual"]["evaluated_count"] = -1
    elif case == "forged_zero_expected":
        row["actual"]["evaluated_count"] = row["expected"]["evaluated_count"] = 0
    else: raise AssertionError(case)
    conn.execute("""UPDATE qa.check_result SET result=%s,affected_count=%s,actual=%s,expected=%s,evidence=%s
        WHERE batch_id=%s AND rule_id=%s AND object_key=%s""", (row["result"], row["affected_count"], Jsonb(row["actual"]),
                                     Jsonb(row["expected"]), Jsonb(row["evidence"]), batch, row["rule_id"], row["object_key"]))


@pytest.mark.parametrize("case", CASES)
def test_gate_rejects_fault_and_keeps_running_batch(prepared, frozen, case):
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as conn:
        conn.execute("SET LOCAL ROLE arsia_loader")
        context = start(conn, prepared, frozen)
        assert len(validate_publication_gate(ModuleConnection(conn), context.batch_id, frozen.as_dict())) == 7
        conn.execute("RESET ROLE")
        mutate(conn, context.batch_id, case)
        conn.execute("SET LOCAL ROLE arsia_loader")
        assert conn.execute("SELECT current_user").fetchone() == ("arsia_loader",)
        with pytest.raises(IntakeError) as error:
            publish(ModuleConnection(conn), context)
        assert error.value.code.startswith("PUBLICATION_QA")
        if case.startswith("other_") or case in {"source_without_year", "missing_summary_reference"}:
            assert error.value.code == "PUBLICATION_QA_EVIDENCE"
        if case in {"required_block", "extra_block"}:
            assert error.value.code == "PUBLICATION_QA_BLOCK"
        assert conn.execute("SELECT status FROM meta.batch WHERE batch_id=%s", (context.batch_id,)).fetchone() == ("running",)
        assert conn.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
        context.evidence.write_json("rejected.json", {"case": case, "code": error.value.code})
        conn.rollback()


@pytest.mark.parametrize("field,value", [("input_fingerprint", "0"*64), ("dataset_kind", "official")])
def test_context_mismatch_rejected(connection, prepared, frozen, field, value):
    context = start(connection, prepared, frozen)
    with pytest.raises(IntakeError) as error:
        publish(ModuleConnection(connection), replace(context, **{field: value}))
    assert error.value.code == "PUBLICATION_CONTEXT"
    assert connection.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)


def test_rollback_preserves_previous_release(connection, prepared, frozen):
    context = start(connection, prepared, frozen)
    old = str(uuid4())
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
        admin.execute("""INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest,status,finished_at)
            VALUES (%s,'synthetic',%s,%s,'succeeded',clock_timestamp())""", (old, "b"*64, Jsonb(frozen.as_dict())))
        admin.execute("INSERT INTO meta.current_release(dataset_kind,batch_id) VALUES ('synthetic',%s)", (old,))
    try:
        result = publish(ModuleConnection(connection), context)
        assert result["batch_id"] == context.batch_id
        connection.rollback()
        assert str(connection.execute("SELECT batch_id FROM meta.current_release").fetchone()[0]) == old
    finally:
        connection.rollback()
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
            admin.execute("DELETE FROM meta.current_release WHERE batch_id=%s", (old,))
            admin.execute("DELETE FROM meta.batch WHERE batch_id=%s", (old,))
