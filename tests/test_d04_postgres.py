"""D04 integration with real C09 Canonical and D03 facts."""

from dataclasses import replace
import os
from pathlib import Path

import pytest

from arsia_d03 import runner_callback as load_dw
from arsia_d04 import reconcile, runner_callback as run_qa06
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import ModuleConnection, RunEvidence
from ac_support import ROOT, interface_manifest
from test_ac_integration_postgres import begin, through_canonical
from test_raw_load_postgres import connection


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="D04 acceptance requires migrated PostgreSQL 16 and ARSIA_TEST_DSN",
)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = Path(tmp_path_factory.mktemp("d04"))
    result = prepare(ROOT / "tests/fixtures/s0/config.json", root / "native-intake")
    assert result["status"] == "prepared" and result["raw_count"] == 19
    return Path(result["run_dir"]), root


@pytest.fixture
def frozen(prepared):
    value = interface_manifest(prepared[0])
    assert type(value) is FrozenManifest
    return value


def loaded(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    projected = through_canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (2, 3)
    dw_context = replace(context, evidence=context.evidence.for_stage("dw"))
    assert load_dw(ModuleConnection(connection), dw_context)["fact_crash"] == 2
    return context


def row(report, source, year):
    return next(
        item for item in report.rows
        if item["object_key"] == f"source_year:{source}:{year}"
    )


def test_real_c09_d03_qa06_writes_all_source_years(
    connection, prepared, frozen
):
    context = loaded(connection, prepared, frozen)
    qa_context = replace(context, evidence=context.evidence.for_stage("qa_d"))
    counts = run_qa06(ModuleConnection(connection), qa_context)

    assert counts == {
        "qa06_object_count": 15,
        "qa06_pass_count": 15,
        "qa06_block_count": 0,
    }
    results = connection.execute(
        """SELECT object_key,result,affected_count,actual,expected,evidence
             FROM qa.check_result
            WHERE batch_id=%s AND rule_id='QA06_RECONCILIATION'
            ORDER BY object_key""",
        (context.batch_id,),
    ).fetchall()
    assert len(results) == 16
    assert all(item[1] == "pass" and item[2] == 0 for item in results)
    assert connection.execute(
        """SELECT count(*) FROM qa.check_result
            WHERE batch_id=%s AND rule_id='QA06_RECONCILIATION'
              AND object_key LIKE 'source_year:%%'""",
        (context.batch_id,),
    ).fetchone() == (15,)
    assert connection.execute(
        """SELECT actual->>'evaluated_count'
             FROM qa.check_result
            WHERE batch_id=%s AND rule_id='QA06_RECONCILIATION'
              AND object_key='source_year:syn_vic:2024'""",
        (context.batch_id,),
    ).fetchone() == ("0",)


def test_swapped_payload_is_found_even_when_aggregates_match(
    connection, prepared, frozen
):
    context = loaded(connection, prepared, frozen)
    facts = connection.execute(
        """SELECT crash_key,severity_code FROM dw.fact_crash
            WHERE batch_id=%s AND source_id='syn_nsw'
            ORDER BY crash_key""",
        (context.batch_id,),
    ).fetchall()
    assert len(facts) == 2 and facts[0][1] != facts[1][1]
    connection.execute(
        """UPDATE dw.fact_crash
              SET severity_code = CASE crash_key
                  WHEN %s THEN %s WHEN %s THEN %s END
            WHERE batch_id=%s AND source_id='syn_nsw'""",
        (facts[0][0], facts[1][1], facts[1][0], facts[0][1], context.batch_id),
    )

    report = reconcile(
        ModuleConnection(connection), context.batch_id, frozen.as_dict(),
        evidence=RunEvidence(context.evidence.directory / "qa-d-swapped"),
    )
    result = row(report, "syn_nsw", 2020)
    assert result["result"] == "block"
    assert result["actual"]["metrics"]["field_mismatch_count"] == 2
    for name in (
        "crash_delta", "fatal_crash_delta", "fatality_delta",
        "casualty_delta", "fatal_crash_known_delta",
        "fatality_known_delta", "casualty_known_delta",
    ):
        assert result["actual"]["metrics"][name] == 0
    assert result["evidence"]["references"][1]["row_count"] == 2


def test_wrong_source_year_creates_missing_and_extra_objects(
    connection, prepared, frozen
):
    context = loaded(connection, prepared, frozen)
    changed = connection.execute(
        """UPDATE dw.fact_crash SET occurrence_year=2021
            WHERE batch_id=%s AND source_id='syn_nsw' AND month_id IS NULL
            RETURNING crash_key""",
        (context.batch_id,),
    ).fetchall()
    assert len(changed) == 1

    report = reconcile(
        ModuleConnection(connection), context.batch_id, frozen.as_dict(),
        evidence=RunEvidence(context.evidence.directory / "qa-d-year"),
    )
    year_2020 = row(report, "syn_nsw", 2020)
    year_2021 = row(report, "syn_nsw", 2021)
    assert year_2020["actual"]["metrics"]["missing_fact_count"] == 1
    assert year_2020["actual"]["metrics"]["crash_delta"] == -1
    assert year_2021["actual"]["metrics"]["extra_fact_count"] == 1
    assert year_2021["actual"]["metrics"]["crash_delta"] == 1


def test_definition_error_and_caller_rollback(
    connection, prepared, frozen
):
    context = loaded(connection, prepared, frozen)
    connection.execute(
        """UPDATE dw.dim_severity SET definition_version='wrong-version'
            WHERE batch_id=%s AND source_id='syn_nsw' AND severity_code='F'""",
        (context.batch_id,),
    )
    report = reconcile(
        ModuleConnection(connection), context.batch_id, frozen.as_dict(),
        evidence=RunEvidence(context.evidence.directory / "qa-d-definition"),
    )
    result = row(report, "syn_nsw", 2020)
    assert result["actual"]["metrics"]["definition_error_count"] == 1
    assert result["result"] == "block"

    qa_context = replace(
        context,
        evidence=RunEvidence(context.evidence.directory / "qa-d-persist"),
    )
    run_qa06(ModuleConnection(connection), qa_context)
    assert connection.execute(
        """SELECT count(*) FROM qa.check_result
            WHERE batch_id=%s AND rule_id='QA06_RECONCILIATION'""",
        (context.batch_id,),
    ).fetchone() == (16,)
    connection.rollback()
    assert connection.execute(
        """SELECT count(*) FROM qa.check_result
            WHERE batch_id=%s AND rule_id='QA06_RECONCILIATION'""",
        (context.batch_id,),
    ).fetchone() == (0,)
