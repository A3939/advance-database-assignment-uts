"""D03 integration with real C09 Canonical data and D02 dimensions."""

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from arsia_d02 import runner_callback as load_dimensions
from arsia_d03 import FactContractError, load_facts, runner_callback
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import ModuleConnection, RunEvidence
from ac_support import ROOT, interface_manifest
from d_acceptance_support import connection, fault_injection
from test_ac_integration_postgres import begin, through_canonical


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="D03 acceptance requires migrated PostgreSQL 16 and ARSIA_TEST_DSN",
)


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = Path(tmp_path_factory.mktemp("d03"))
    result = prepare(ROOT / "tests/fixtures/s0/config.json", root / "native-intake")
    assert result["status"] == "prepared" and result["raw_count"] == 19
    return Path(result["run_dir"]), root


@pytest.fixture
def frozen(prepared):
    value = interface_manifest(prepared[0])
    assert type(value) is FrozenManifest
    return value


def call_dw(connection, context):
    child = replace(context, evidence=context.evidence.for_stage("dw"))
    return runner_callback(ModuleConnection(connection), child)


def facts(connection, batch_id):
    return connection.execute(
        """
        SELECT
            batch_id, source_id, release_scope, crash_key,
            occurrence_year, month_id, severity_code,
            is_fatal_crash, fatality_count, casualty_count,
            fatal_crash_eligible, fatality_eligible, casualty_eligible,
            latitude, longitude, map_eligible
        FROM dw.fact_crash
        WHERE batch_id = %s
        ORDER BY source_id, release_scope, crash_key
        """,
        (batch_id,),
    ).fetchall()


def expected_facts(connection, batch_id):
    return connection.execute(
        """
        SELECT
            batch_id, source_id, release_scope, crash_key,
            occurrence_year,
            CASE WHEN occurrence_month IS NULL THEN NULL
                 ELSE occurrence_year * 100 + occurrence_month END,
            severity_code, is_fatal_crash, fatality_count, casualty_count,
            fatal_crash_eligible, fatality_eligible, casualty_eligible,
            latitude, longitude, map_eligible
        FROM canonical.crash
        WHERE batch_id = %s
        ORDER BY source_id, release_scope, crash_key
        """,
        (batch_id,),
    ).fetchall()


def test_real_c09_d02_d03_one_to_one_without_unit_inflation(
    connection, prepared, frozen
):
    context = begin(connection, prepared, frozen)
    projected = through_canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (2, 3)

    result = call_dw(connection, context)
    assert result == {
        "dim_source": 3,
        "dim_month": 60,
        "dim_severity": 12,
        "fact_crash": 2,
    }
    assert facts(connection, context.batch_id) == expected_facts(
        connection, context.batch_id
    )
    assert [row[5] for row in facts(connection, context.batch_id)] == [202001, None]

    evidence = json.loads(
        (
            context.evidence.directory
            / "dw"
            / "d03-fact-crash.json"
        ).read_text(encoding="utf-8")
    )
    assert evidence["fact_count"] == 2
    assert evidence["canonical_reconciled"] is True
    assert evidence["unit_rows_joined"] is False


def test_combined_dw_callback_is_idempotent(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    through_canonical(connection, context)
    first = call_dw(connection, context)
    before = facts(connection, context.batch_id)

    repeat = replace(
        context,
        evidence=RunEvidence(context.evidence.directory / "dw-repeat"),
    )
    second = runner_callback(ModuleConnection(connection), repeat)
    assert second == first
    assert facts(connection, context.batch_id) == before


def test_dimension_definition_mismatch_blocks_facts(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    through_canonical(connection, context)
    dw_context = replace(context, evidence=context.evidence.for_stage("dw"))
    assert load_dimensions(
        ModuleConnection(connection), dw_context
    )["dim_severity"] == 12
    with fault_injection(connection):
        connection.execute(
            """UPDATE dw.dim_severity SET definition_version='wrong-version'
                WHERE batch_id=%s AND source_id='syn_nsw'
                  AND severity_code='F'""",
            (context.batch_id,),
        )

    with pytest.raises(FactContractError) as error:
        load_facts(ModuleConnection(connection), context.batch_id)
    assert error.value.code == "D03_DIMENSION_CONTRACT"
    assert error.value.details["failures"] == {
        "severity_definition_mismatch": 1
    }
    assert facts(connection, context.batch_id) == []


def test_caller_rollback_removes_dimensions_and_facts(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    through_canonical(connection, context)
    call_dw(connection, context)
    connection.rollback()

    for table in ("dw.dim_source", "dw.dim_severity", "dw.fact_crash"):
        assert connection.execute(
            f"SELECT count(*) FROM {table} WHERE batch_id = %s",
            (context.batch_id,),
        ).fetchone() == (0,)
