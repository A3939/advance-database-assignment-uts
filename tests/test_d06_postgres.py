"""Opt-in D06 checks against the real C09 -> D03 database path."""

from dataclasses import replace
import os

import pytest

from arsia_d03 import runner_callback as load_dw
from arsia_d06 import SeverityRequest, query_severity
from arsia_ingest.runner import ModuleConnection
from d_acceptance_support import connection
from test_d04_postgres import prepared, frozen
from test_ac_integration_postgres import begin, through_canonical


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="D06 acceptance requires migrated PostgreSQL 16 and ARSIA_TEST_DSN",
)


def _deployed(connection):
    signature = connection.execute(
        """SELECT to_regprocedure(
            'published.d06_severity(text,uuid,text[],integer,integer,integer[])'
        )"""
    ).fetchone()[0]
    if signature is None:
        pytest.skip("Deploy src/arsia_d06/sql/d06_severity.sql before acceptance")


def _loaded(connection, prepared, frozen, *, succeeded=True):
    _deployed(connection)
    context = begin(connection, prepared, frozen)
    projected = through_canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (2, 3)
    dw_context = replace(context, evidence=context.evidence.for_stage("dw"))
    assert load_dw(ModuleConnection(connection), dw_context)["fact_crash"] == 2
    if succeeded:
        connection.execute(
            """UPDATE meta.batch
                  SET status='succeeded', finished_at=now()
                WHERE batch_id=%s""",
            (context.batch_id,),
        )
    return context


def test_real_nsw_groups_keep_missing_and_match_facts(
    connection, prepared, frozen
):
    context = _loaded(connection, prepared, frozen)
    rows = query_severity(
        ModuleConnection(connection),
        SeverityRequest("synthetic", context.batch_id, source_ids=("syn_nsw",)),
    )

    assert len(rows) == 2
    assert {row["severity_code"] for row in rows} == {"F", "__MISSING__"}
    assert sum(row["crash_count"] for row in rows) == 2
    expected = {
        (code, label, version, text)
        for code, label, version, text in connection.execute(
            """SELECT severity_code,severity_label,definition_version,
                      definition_text
                 FROM dw.dim_severity
                WHERE batch_id=%s AND source_id='syn_nsw'
                  AND severity_code IN ('F','__MISSING__')""",
            (context.batch_id,),
        ).fetchall()
    }
    actual = {
        (
            row["severity_code"], row["severity_label"],
            row["definition_version"], row["definition_text"],
        )
        for row in rows
    }
    assert actual == expected


def test_month_filter_excludes_unknown_month_group(connection, prepared, frozen):
    context = _loaded(connection, prepared, frozen)
    rows = query_severity(
        ModuleConnection(connection),
        SeverityRequest(
            "synthetic", context.batch_id, source_ids=("syn_nsw",),
            year_from=2020, year_to=2020, months=(1,),
        ),
    )
    assert len(rows) == 1
    assert rows[0]["severity_code"] == "F"
    assert rows[0]["crash_count"] == 1
    assert rows[0]["filter_months"] == [1] or rows[0]["filter_months"] == (1,)


def test_running_batch_is_rejected(connection, prepared, frozen):
    import psycopg

    context = _loaded(connection, prepared, frozen, succeeded=False)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="D06_BATCH_STATUS"):
        query_severity(
            ModuleConnection(connection),
            SeverityRequest("synthetic", context.batch_id),
        )


def test_wrong_dataset_mode_is_rejected(connection, prepared, frozen):
    import psycopg

    context = _loaded(connection, prepared, frozen)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="D06_BATCH_MODE"):
        query_severity(
            ModuleConnection(connection),
            SeverityRequest("official", context.batch_id),
        )
