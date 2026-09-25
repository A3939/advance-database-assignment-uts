"""Real QA07 year coverage with unchanged foreign keys and loader grants."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from arsia_c import qa
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from arsia_ingest.runner import ModuleBinding, ModuleConnection
from cd_support import ROOT, bindings, interface_manifest
from test_raw_load_postgres import connection
from test_cd_integration_postgres import prepared, canonical, call, cleanup, full_snapshot
from test_ac_integration_postgres import begin, counts, TABLES, raw_rows

pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Use the private C10 PostgreSQL verifier",
)


@pytest.fixture
def frozen(prepared):
    value = interface_manifest(prepared[0]).as_dict()
    # C's verifier overlays its fragment on a pinned B checkout.
    fragment = ROOT / "config/c10-inventory.json"
    if fragment.exists():
        declared = {e["path"]: e for e in value["rules"]["code_files"]}
        for entry in json.loads(fragment.read_text(encoding="utf-8"))["code_files"]:
            assert hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
            declared[entry["path"]] = entry
        value["rules"]["code_files"] = list(declared.values())
    return FrozenManifest(json.dumps(value))


@pytest.fixture(autouse=True)
def private_database(connection):
    assert connection.execute(
        "SELECT current_user,session_user,current_setting('arsia.test_run',true)"
    ).fetchone() == ("arsia_loader", "arsia_loader", os.environ["AC_TEST_RUN"])
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    connection.rollback()


def chain(conn, prepared, frozen):
    context = begin(conn, prepared, frozen)
    canonical(conn, context)
    call(conn, context, "dw")
    return replace(context, evidence=context.evidence.for_stage("qa_c"))


def invoke(conn, context):
    binding = bindings().get("qa_c")
    if binding is None:
        binding = ModuleBinding(qa.runner_callback, "src/arsia_c/qa.py", qa.PRODUCER_VERSION)
    assert binding.callback is qa.runner_callback and binding.version == qa.PRODUCER_VERSION
    return binding.callback(ModuleConnection(conn), context)


def insert_extra(conn, context, source, year, *, with_fact=True):
    """Insert a corrupt extra crash without disabling constraints or changing grants."""
    from psycopg.types.json import Jsonb

    key = conn.execute("SELECT rv.encode_business_key(%s)", ("qa07-extra-" + uuid4().hex,)).fetchone()[0]
    patches = {
        "rv.hub_crash": {"crash_key": key},
        "rv.sat_crash": {"crash_key": key},
        "canonical.crash": {"crash_key": key, "occurrence_year": year,
                            "occurrence_month": None, "occurrence_date": None, "date_precision": "year"},
        "dw.fact_crash": {"crash_key": key, "occurrence_year": year, "month_id": None},
    }
    for table, patch in patches.items():
        if table == "dw.fact_crash" and not with_fact:
            continue
        batch_column = "first_seen_batch_id" if table == "rv.hub_crash" else "batch_id"
        # Table names above are fixed test constants, not external input.
        changed = conn.execute(
            f"INSERT INTO {table} SELECT (jsonb_populate_record(NULL::{table}, "
            f"to_jsonb(t) || %s)).* FROM {table} t WHERE {batch_column}=%s AND source_id=%s "
            "AND crash_key<>%s ORDER BY crash_key LIMIT 1",
            (Jsonb(patch), context.batch_id, source, key),
        ).rowcount
        assert changed == 1
    return key


def run_and_save(conn, context, label):
    error_code = None
    try:
        invoke(conn, context)
    except IntakeError as error:
        error_code = error.code
    rows = conn.execute(
        "SELECT rule_id,object_key,result,affected_count,actual,expected,evidence "
        "FROM qa.check_result WHERE batch_id=%s ORDER BY rule_id,object_key", (context.batch_id,),
    ).fetchall()
    context.evidence.write_json("year-coverage-observed.json", {
        "case": label, "callback_error": error_code,
        "rows": [dict(zip(("rule", "object", "result", "affected", "actual", "expected", "evidence"), r))
                 for r in rows],
    })
    return error_code, rows


def assert_year_block(conn, context, source, year, key):
    error_code, rows = run_and_save(conn, context, f"{source}:{year}")
    assert error_code == "C10_BLOCK"
    summary = next(r for r in rows if r[:2] == ("QA07_LOCATION", "batch"))
    assert summary[2] == "block", "QA07 must not omit the out-of-range crash"
    row = next(r for r in rows if r[:2] == ("QA07_LOCATION", f"source_year:{source}:{year}"))
    assert row[2] == "block" and row[3] > 0
    assert row[4]["violation_count"] == row[3]
    assert row[5]["evaluated_count"] == 0 and row[5]["metrics"]["crash_count"] == 0
    assert "outside_analysis_year" in row[6]["reason_codes"]
    references = [r for r in row[6]["references"] if "path" in r]
    assert references
    details = []
    for ref in references:
        data = Path(ref["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == ref["sha256"]
        details.extend(json.loads(data)["rows"])
    assert any("outside_analysis_year" in d["reason_codes"]
               and any(r["crash_key"] == key for r in d["actual"]) for d in details)
    assert conn.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    conn.rollback()
    assert counts(conn) == dict.fromkeys(TABLES, 0)
    assert all(Path(r["path"]).is_file() for r in references)


@pytest.mark.parametrize("source", ["syn_nsw", "syn_vic", "syn_qld"])
@pytest.mark.parametrize("year", [2019, 2025])
def test_extra_fact_outside_analysis_blocks_qa07(connection, prepared, frozen, source, year):
    context = chain(connection, prepared, frozen)
    before_raw = raw_rows(connection)
    key = insert_extra(connection, context, source, year)
    assert raw_rows(connection) == before_raw
    assert connection.execute(
        "SELECT count(*) FROM dw.fact_crash WHERE batch_id=%s", (context.batch_id,),
    ).fetchone() == (7,)
    assert_year_block(connection, context, source, year, key)


def test_canonical_only_outside_analysis_also_blocks(connection, prepared, frozen):
    context = chain(connection, prepared, frozen)
    key = insert_extra(connection, context, "syn_qld", 2025, with_fact=False)
    assert_year_block(connection, context, "syn_qld", 2025, key)


@pytest.mark.parametrize("years", [(2020, 2021), (2021, 2024)])
def test_inclusive_boundaries_and_retained_raw_are_allowed(connection, prepared, frozen, years):
    value = frozen.as_dict()
    value["analysis"] = dict(zip(("year_from", "year_to"), years))
    context = chain(connection, prepared, FrozenManifest(json.dumps(value)))
    before = raw_rows(connection)
    error_code, rows = run_and_save(connection, context, f"allowed:{years}")
    assert error_code is None and all(r[2] != "block" for r in rows)
    expected = {f"source_year:{s['source_id']}:{y}" for s in value["sources"]
                for y in range(years[0], years[1] + 1)}
    assert {r[1] for r in rows if r[0] == "QA07_LOCATION" and r[1] != "batch"} == expected
    assert raw_rows(connection) == before and len(before) == 19
    connection.rollback()
    assert not any(counts(connection).values())


def test_other_batch_outside_year_is_ignored_and_preserved(connection, prepared, frozen):
    batches = []
    try:
        first = chain(connection, prepared, frozen)
        batches.append(first.batch_id)
        insert_extra(connection, first, "syn_qld", 2019)
        connection.commit()  # Unpublished diagnostic fixture, not a successful release.
        before = full_snapshot(connection, first.batch_id)
        current = chain(connection, prepared, frozen)
        batches.append(current.batch_id)
        error_code, rows = run_and_save(connection, current, "other-batch")
        assert error_code is None and all(r[2] != "block" for r in rows)
        assert not any(r[1].endswith(":2019") for r in rows)
        assert full_snapshot(connection, first.batch_id) == before
        connection.rollback()
        assert full_snapshot(connection, first.batch_id) == before
        assert not any(full_snapshot(connection, current.batch_id).values())
    finally:
        connection.rollback()
        cleanup(batches, frozen)
    assert not any(counts(connection).values())
