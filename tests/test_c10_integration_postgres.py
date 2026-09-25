"""C10 through B's installed binding; combined QA01-07 acceptance is separate."""

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from arsia_c import qa
from arsia_ingest.components import bindings
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from arsia_ingest.runner import ModuleConnection
from test_raw_load_postgres import connection
from test_cd_integration_postgres import prepared, frozen, private_database, canonical, call
from test_ac_integration_postgres import begin, counts, TABLES

pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Use tools/verify_c10_integration_postgres.py for private PG16",
)


def chain(conn, prepared, frozen):
    context = begin(conn, prepared, frozen)
    canonical(conn, context)
    assert call(conn, context, "dw") == {
        "dim_source": 3, "dim_month": 60, "dim_severity": 12, "fact_crash": 6,
    }
    return replace(context, evidence=context.evidence.for_stage("qa_c"))


def invoke(conn, context):
    return bindings()["qa_c"].callback(ModuleConnection(conn), context)


def results(conn, context):
    return conn.execute(
        "SELECT rule_id,object_key,result,actual,expected,evidence FROM qa.check_result "
        "WHERE batch_id=%s ORDER BY rule_id,object_key", (context.batch_id,),
    ).fetchall()


def test_installed_binding_persists_evidence_and_caller_can_rollback(connection, prepared, frozen):
    assert type(frozen) is FrozenManifest
    context = chain(connection, prepared, frozen)
    assert invoke(connection, context) == {
        "c10_object_count": 27, "c10_summary_count": 4, "limited_count": 2,
    }
    rows = results(connection, context)
    assert len(rows) == 31
    objects = [r for r in rows if r[1] != "batch"]
    assert {r[0] for r in objects} == set(qa.RULES)
    assert sum(r[2] == "limited" for r in objects) == 2
    assert all(r[2] == "pass" for r in objects if r[0] != "QA07_LOCATION")
    locations = [r for r in objects if r[0] == "QA07_LOCATION"]
    assert len(locations) == 15
    assert sum(r[3]["evaluated_count"] == 0 for r in locations) == 10
    summaries = [r for r in rows if r[1] == "batch"]
    assert len(summaries) == 4 and not any(r[2] == "block" for r in rows)
    for _, _, _, actual, expected, evidence in rows:
        assert actual["violation_count"] == 0
        assert actual["evaluated_count"] == expected["evaluated_count"]
        assert evidence["producer_version"] == qa.PRODUCER_VERSION
        assert evidence["references"]
        for ref in evidence["references"]:
            if "path" in ref:
                assert hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest() == ref["sha256"]
    saved = context.evidence.directory / "c10-results.json"
    assert json.loads(saved.read_text(encoding="utf-8"))["batch_id"] == context.batch_id
    assert connection.execute("SELECT count(*) FROM meta.current_release").fetchone() == (0,)
    with pytest.raises(IntakeError) as error:
        invoke(connection, context)
    assert error.value.code == "C10_EXISTS"
    connection.rollback()
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    assert saved.is_file()


@pytest.mark.parametrize("change", ["batch_id", "dataset_kind"])
def test_context_mismatch_is_rejected(connection, prepared, frozen, change):
    context = chain(connection, prepared, frozen)
    altered = replace(context, **{change: str(uuid4()) if change == "batch_id" else "official"})
    with pytest.raises(IntakeError) as error:
        invoke(connection, altered)
    assert error.value.code == "C10_INPUT"
    assert not results(connection, context)
    connection.rollback()
    assert not any(counts(connection).values())


def test_block_keeps_file_evidence_and_rolls_back_database_rows(connection, prepared, frozen):
    context = chain(connection, prepared, frozen)
    # The loader owns its temporary projection table; no extra grants are needed.
    changed = connection.execute(
        "DELETE FROM pg_temp.arsia_i_crash WHERE source_id='syn_qld' AND occurrence_year=2021"
    ).rowcount
    assert changed == 1
    with pytest.raises(IntakeError) as error:
        invoke(connection, context)
    assert error.value.code == "C10_BLOCK"
    rows = results(connection, context)
    assert len(rows) == 31
    assert any(r[:3] == ("QA03_PROJECTED", "batch", "block") for r in rows)
    ref = error.value.details["evidence_ref"]
    saved = Path(ref["path"])
    assert hashlib.sha256(saved.read_bytes()).hexdigest() == ref["sha256"]
    connection.rollback()
    assert counts(connection) == dict.fromkeys(TABLES, 0)
    assert saved.is_file()


def test_loader_keeps_original_append_only_permissions(connection, prepared, frozen):
    import psycopg

    context = chain(connection, prepared, frozen)
    invoke(connection, context)
    for statement in ("UPDATE qa.check_result SET result='pass'", "DELETE FROM qa.check_result"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with connection.transaction():
                connection.execute(statement)
    assert len(results(connection, context)) == 31
    connection.rollback()
    assert not any(counts(connection).values())
