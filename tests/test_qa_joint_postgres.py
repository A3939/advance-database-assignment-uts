"""Run all seven real QA producers in one unpublished S0 component transaction."""
from collections import Counter
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from arsia_ingest.manifest import FrozenManifest, REQUIRED_CHECKS, s0_definitions
from arsia_ingest.models import IntakeError
from arsia_ingest.qa_input import check_inputs, check_raw, write_results
from arsia_ingest.runner import ModuleConnection, RunEvidence, _qa_summary
from cd_support import ROOT
from test_raw_load_postgres import connection
from test_cd_integration_postgres import prepared, frozen, private_database, call, cleanup, full_snapshot
from test_ac_integration_postgres import begin, counts, raw_rows, assert_empty_from_new_session

pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Use tools/verify_qa_joint_postgres.py for private PostgreSQL 16",
)

METRICS = {
    "QA01_INPUT": "hash_match header_match bundle_confirmed contract_confirmed",
    "QA02_RAW": "raw_count distinct_locator_count payload_mismatch_count",
    "QA03_PROJECTED": "input_count excluded_count projected_count duplicate_key_count orphan_count invalid_value_count",
    "QA04_AUXILIARY": "orphan_count nonblank_unmatched_count declared_count_delta duplicate_group_count coordinate_conflict_group_count",
    "QA05_SEMANTICS": "undefined_category_count unconfirmed_definition_count eligibility_error_count",
    "QA06_RECONCILIATION": "missing_fact_count extra_fact_count field_mismatch_count lineage_error_count definition_error_count crash_delta fatal_crash_delta fatality_delta casualty_delta fatal_crash_known_delta fatality_known_delta casualty_known_delta",
    "QA07_LOCATION": "crash_count map_count unmapped_count invalid_eligible_count",
}


def expected_objects(value):
    """Derive test expectations from the frozen scope, independently of QA output."""
    files = value["files"]
    file_keys = {f"file:{f['resource_id']}:{f['file_sha256']}:{f['parser_version']}" for f in files}
    years = {f"source_year:{s['source_id']}:{y}" for s in value["sources"]
             for y in range(value["analysis"]["year_from"], value["analysis"]["year_to"] + 1)}
    return {
        "QA01_INPUT": file_keys, "QA02_RAW": file_keys,
        "QA03_PROJECTED": {"resource:" + f["resource_id"] for f in files if f["entity_kind"] in {"crash", "unit"}},
        "QA04_AUXILIARY": {"resource:" + f["resource_id"] for f in files if f["entity_kind"] in {"unit", "person_raw", "node_raw"}},
        "QA05_SEMANTICS": {"source:" + s["source_id"] for s in value["sources"]},
        "QA06_RECONCILIATION": years, "QA07_LOCATION": years,
    }


def stored(conn, context):
    return [r[0] for r in conn.execute(
        "SELECT to_jsonb(q) FROM qa.check_result q WHERE batch_id=%s ORDER BY rule_id,object_key",
        (context.batch_id,),
    )]


def check_refs(value):
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            data = Path(value["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == value["sha256"]
            if Path(value["path"]).suffix == ".jsonl":
                assert len(data.splitlines()) == value["row_count"]
            if "detail_row_count" in value:
                assert len(json.loads(data)["rows"]) == value["detail_row_count"]
        for child in value.values():
            check_refs(child)
    elif isinstance(value, list):
        for child in value:
            check_refs(child)


def assert_coverage(rows, value):
    expected = {(rule, key) for rule, keys in expected_objects(value).items() for key in keys | {"batch"}}
    actual = [(r["rule_id"], r["object_key"]) for r in rows]
    assert len(actual) == len(set(actual))
    assert set(actual) == expected, "Seven summaries do not prove complete concrete-object coverage"


def check_complete(conn, context):
    rows = stored(conn, context)
    assert_coverage(rows, context.manifest.as_dict())
    for rule, keys in expected_objects(context.manifest.as_dict()).items():
        group = [r for r in rows if r["rule_id"] == rule and r["object_key"] != "batch"]
        summary = next(r for r in rows if (r["rule_id"], r["object_key"]) == (rule, "batch"))
        states = Counter(r["result"] for r in group)
        assert not states["block"]
        assert summary["actual"]["metrics"] == {
            "object_count": len(keys), "pass_count": states["pass"], "limited_count": states["limited"],
            "block_count": 0, "missing_count": 0,
        }
        assert summary["actual"]["evaluated_count"] == summary["expected"]["evaluated_count"] == len(keys)
        assert summary["affected_count"] == sum(r["affected_count"] for r in group)
        assert summary["result"] == ("limited" if states["limited"] else "pass")
        for row in group:
            assert row["batch_id"] == context.batch_id
            actual, expected = row["actual"], row["expected"]
            assert set(actual["metrics"]) == set(expected["metrics"]) == set(METRICS[rule].split())
            assert actual["evaluated_count"] == expected["evaluated_count"]
            assert actual["violation_count"] == expected["violation_count"] == 0
            for key, wanted in expected["metrics"].items():
                if wanted is not None:
                    assert actual["metrics"][key] == wanted
            assert row["result"] in {"pass", "limited"}
            assert row["evidence"]["producer_version"] and row["evidence"]["references"]
            if row["result"] == "limited":
                assert rule == "QA07_LOCATION"
                assert row["affected_count"] == actual["metrics"]["unmapped_count"] > 0
                assert row["evidence"]["reason_codes"]
            else:
                assert row["affected_count"] == 0
            if rule == "QA07_LOCATION" and actual["evaluated_count"] == 0:
                assert next(r["coverage"] for r in row["evidence"]["references"] if "coverage" in r) is None
    check_refs(rows)
    summary = _qa_summary(ModuleConnection(conn), context.batch_id)
    assert [r["rule_id"] for r in summary] == list(REQUIRED_CHECKS)
    return rows, summary


def input_check(prepared, frozen, evidence):
    report = check_inputs(
        frozen.as_dict(), prepared[0].parents[2], previous_manifest=None,
        evidence_dir=evidence.for_stage("input").directory, producer_version="b11-v1",
        supported_mappings=s0_definitions(ROOT / "tests/fixtures/s0/contract.json")["mappings"],
    )
    evidence.write_json("qa01.json", report.as_dict())
    return report


def load_chain(conn, prepared, frozen):
    evidence = RunEvidence(prepared[1] / "joint-runs" / uuid4().hex)
    inputs = input_check(prepared, frozen, evidence)
    assert not inputs.blocked
    # Use B's real registration inputs. This UUID-based test identifier is not FP1.
    context = replace(begin(conn, prepared, frozen), evidence=evidence)
    evidence.write_json("manifest.json", frozen.as_dict())
    for stage in ("project", "vault", "canonical", "dw"):
        call(conn, context, stage)
    return context, inputs


def b_results(conn, prepared, context, inputs):
    raw = check_raw(ModuleConnection(conn), context.manifest.as_dict(), prepared[0].parents[2],
                    evidence_dir=context.evidence.for_stage("raw").directory, producer_version="b11-v1")
    context.evidence.write_json("qa02.json", raw.as_dict())
    # Diagnostic tests persist a blocked report too; the normal runner stops before this.
    for report in (inputs, raw):
        write_results(ModuleConnection(conn), context.batch_id, report)
    return raw


def finish(conn, prepared, context, inputs):
    assert not b_results(conn, prepared, context, inputs).blocked
    call(conn, context, "qa_c")
    call(conn, context, "qa_d")
    rows, summaries = check_complete(conn, context)
    context.evidence.write_json("joint-result.json", {
        "scope": "S0 component transaction; no FP1, publication or final platform freeze",
        "batch_id": context.batch_id, "manifest_type": type(context.manifest).__name__,
        "rows": rows, "qa_summary": summaries,
    })
    assert conn.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    return rows, summaries


@pytest.mark.parametrize("year_from,expected_rows,crashes,limited", [
    (2020, 63, 6, 2), (2021, 57, 2, 1), (2022, 51, 0, 0),
])
def test_all_seven_groups_share_one_batch(connection, prepared, frozen, year_from, expected_rows, crashes, limited):
    value = frozen.as_dict()
    value["analysis"]["year_from"] = year_from
    manifest = FrozenManifest(json.dumps(value))
    context, inputs = load_chain(connection, prepared, manifest)
    before = raw_rows(connection)
    rows, summaries = finish(connection, prepared, context, inputs)
    assert len(rows) == expected_rows and len(summaries) == 7
    assert sum(r["result"] == "limited" for r in rows if r["object_key"] != "batch") == limited
    assert connection.execute("SELECT count(*) FROM dw.fact_crash").fetchone() == (crashes,)
    assert connection.execute("SELECT count(*) FROM dw.dim_source").fetchone() == (3,)
    assert connection.execute("SELECT count(*) FROM dw.dim_month").fetchone() == ((2025-year_from)*12,)
    assert connection.execute("SELECT count(*) FROM dw.dim_severity").fetchone() == (12,)
    assert len(before) == 19 and raw_rows(connection) == before
    assert_empty_from_new_session()
    connection.rollback()
    assert not any(counts(connection).values())
    assert_empty_from_new_session()
    check_refs(rows)
    assert (context.evidence.directory / "joint-result.json").is_file()


def test_qa01_changed_archive_stops_before_batch(connection, prepared, frozen, tmp_path):
    import shutil

    archive_root = tmp_path / "intake"
    shutil.copytree(prepared[0].parents[2], archive_root)
    file = next(f for f in frozen.as_dict()["files"] if f["resource_id"] == "syn_qld_crash")
    digest = file["file_sha256"]
    archive = archive_root / "synthetic/archive/sha256" / digest[:2] / digest
    archive.write_bytes(archive.read_bytes() + b"\n")
    evidence = RunEvidence(prepared[1] / "joint-input-block" / uuid4().hex)
    report = check_inputs(frozen.as_dict(), archive_root, evidence_dir=evidence.directory,
                          producer_version="b11-v1", supported_mappings=s0_definitions(
                              ROOT / "tests/fixtures/s0/contract.json")["mappings"])
    evidence.write_json("qa01.json", report.as_dict())
    assert report.blocked and report.rows[-1]["result"] == "block"
    assert any("QA_HASH" in row["evidence"]["reason_codes"] for row in report.rows)
    check_refs(report.as_dict())
    assert not any(counts(connection).values())


FAULTS = [
    ("QA02_RAW", "UPDATE raw.record SET payload=jsonb_set(payload,'{Crash_Hour}','\"changed\"') WHERE resource_id='syn_qld_crash' AND row_locator='csv:2'"),
    ("QA03_PROJECTED", "DELETE FROM pg_temp.arsia_i_crash WHERE source_id='syn_qld' AND occurrence_year=2021"),
    ("QA04_AUXILIARY", "UPDATE raw.record SET payload=jsonb_set(payload,'{VEHICLE_ID}','\"unknown\"') WHERE resource_id='syn_vic_person' AND row_locator='csv:2'"),
    ("QA05_SEMANTICS", "UPDATE canonical.unit SET unit_type_code='wrong' WHERE source_id='syn_vic'"),
    ("QA06_RECONCILIATION", "UPDATE dw.fact_crash SET fatality_count=fatality_count+1 WHERE source_id='syn_qld' AND occurrence_year=2020"),
    ("QA07_LOCATION", "UPDATE dw.fact_crash SET latitude=latitude+1 WHERE source_id='syn_qld' AND occurrence_year=2020"),
]


@pytest.mark.parametrize("rule,statement", FAULTS, ids=[f[0] for f in FAULTS])
def test_joint_chain_blocks_each_downstream_group(connection, prepared, frozen, rule, statement):
    import psycopg

    # Only the fault injection uses the private owner. All producers use loader grants.
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        owner.execute("SET LOCAL ROLE arsia_loader")
        context, inputs = load_chain(owner, prepared, frozen)
        if rule != "QA02_RAW":
            assert not b_results(owner, prepared, context, inputs).blocked
        owner.execute("RESET ROLE")
        assert owner.execute(statement).rowcount > 0
        owner.execute("SET LOCAL ROLE arsia_loader")
        assert owner.execute("SELECT current_user").fetchone() == ("arsia_loader",)
        if rule == "QA02_RAW":
            assert b_results(owner, prepared, context, inputs).blocked
        elif rule == "QA06_RECONCILIATION":
            call(owner, context, "qa_c")
            assert call(owner, context, "qa_d")["qa06_block_count"] > 0
        else:
            with pytest.raises(IntakeError) as exc:
                call(owner, context, "qa_c")
            assert exc.value.code == "C10_BLOCK"
        rows = stored(owner, context)
        selected = [r for r in rows if r["rule_id"] == rule]
        assert any(r["object_key"] != "batch" and r["result"] == "block" for r in selected)
        assert next(r for r in selected if r["object_key"] == "batch")["result"] == "block"
        assert all(r["evidence"]["reason_codes"] for r in selected if r["result"] == "block")
        with pytest.raises(IntakeError) as exc:
            _qa_summary(ModuleConnection(owner), context.batch_id)
        assert exc.value.code == "QA_SUMMARY"
        if rule == "QA02_RAW":
            assert {r["rule_id"] for r in rows} == {"QA01_INPUT", "QA02_RAW"}
        elif rule != "QA06_RECONCILIATION":
            assert not any(r["rule_id"] == "QA06_RECONCILIATION" for r in rows)
        check_refs(rows)
        context.evidence.write_json("joint-block.json", {
            "injected_rule": rule, "injection_after_qa02": rule != "QA02_RAW", "rows": rows,
            "later_checks_not_filled": True, "publication_performed": False,
        })
        assert owner.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
        owner.rollback()
    assert not any(counts(connection).values())
    assert_empty_from_new_session()
    check_refs(rows)


@pytest.mark.parametrize("rule", REQUIRED_CHECKS)
def test_missing_summary_is_rejected(connection, prepared, frozen, rule):
    import psycopg

    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        owner.execute("SET LOCAL ROLE arsia_loader")
        context, inputs = load_chain(owner, prepared, frozen)
        finish(owner, prepared, context, inputs)
        owner.execute("RESET ROLE")
        assert owner.execute("DELETE FROM qa.check_result WHERE batch_id=%s AND rule_id=%s AND object_key='batch'",
                             (context.batch_id, rule)).rowcount == 1
        owner.execute("SET LOCAL ROLE arsia_loader")
        with pytest.raises(IntakeError) as exc:
            _qa_summary(ModuleConnection(owner), context.batch_id)
        assert exc.value.code == "QA_SUMMARY"
        context.evidence.write_json("missing-summary.json", {"removed_rule": rule, "rejected": exc.value.code})
        owner.rollback()
    assert not any(counts(connection).values())


def test_summary_transport_does_not_replace_e_object_gate(connection, prepared, frozen):
    import psycopg

    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        owner.execute("SET LOCAL ROLE arsia_loader")
        context, inputs = load_chain(owner, prepared, frozen)
        finish(owner, prepared, context, inputs)
        owner.execute("RESET ROLE")
        assert owner.execute("DELETE FROM qa.check_result WHERE batch_id=%s AND rule_id='QA07_LOCATION' "
                             "AND object_key='source_year:syn_qld:2024'", (context.batch_id,)).rowcount == 1
        owner.execute("SET LOCAL ROLE arsia_loader")
        assert len(_qa_summary(ModuleConnection(owner), context.batch_id)) == 7
        with pytest.raises(AssertionError, match="concrete-object coverage"):
            assert_coverage(stored(owner, context), frozen.as_dict())
        context.evidence.write_json("object-gate-boundary.json", {
            "missing_object": "QA07_LOCATION/source_year:syn_qld:2024",
            "summary_transport_accepts": True, "independent_test_coverage_rejects": True,
            "e_publication_gate_executed": False,
        })
        owner.rollback()
    assert not any(counts(connection).values())


@pytest.mark.parametrize("producer", ["qa01", "qa02", "qa_c", "qa_d"])
def test_second_write_cannot_overwrite_joint_results(connection, prepared, frozen, producer):
    import psycopg

    context, inputs = load_chain(connection, prepared, frozen)
    finish(connection, prepared, context, inputs)
    before = stored(connection, context)
    error = IntakeError if producer == "qa_c" else psycopg.errors.UniqueViolation
    with pytest.raises(error):
        with connection.transaction():
            if producer == "qa01":
                write_results(ModuleConnection(connection), context.batch_id, inputs)
            elif producer == "qa02":
                raw = check_raw(ModuleConnection(connection), frozen.as_dict(), prepared[0].parents[2],
                                evidence_dir=context.evidence.directory / "repeat-raw", producer_version="b11-v1")
                write_results(ModuleConnection(connection), context.batch_id, raw)
            else:
                call(connection, replace(context, evidence=RunEvidence(context.evidence.directory / "repeat")), producer)
    assert stored(connection, context) == before
    connection.rollback()
    assert not any(counts(connection).values())


def test_second_batch_preserves_all_previous_qa(connection, prepared, frozen):
    batches = []
    try:
        first, inputs = load_chain(connection, prepared, frozen)
        batches.append(first.batch_id)
        finish(connection, prepared, first, inputs)
        connection.commit()  # Unpublished diagnostic fixture; not a successful release.
        before = full_snapshot(connection, first.batch_id)
        second, inputs = load_chain(connection, prepared, frozen)
        batches.append(second.batch_id)
        finish(connection, prepared, second, inputs)
        assert len(stored(connection, first)) == len(stored(connection, second)) == 63
        assert full_snapshot(connection, first.batch_id) == before
        connection.rollback()
        assert full_snapshot(connection, first.batch_id) == before
        assert not stored(connection, second)
        assert connection.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    finally:
        connection.rollback()
        cleanup(batches, frozen)
    assert not any(counts(connection).values())
