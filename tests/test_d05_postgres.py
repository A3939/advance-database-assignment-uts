"""Opt-in D05 check against the real C09 -> D03 database path."""

from dataclasses import replace
import os

import pytest

from arsia_d03 import runner_callback as load_dw
from arsia_d05 import TrendRequest, query_trend
from arsia_ingest.runner import ModuleConnection
from test_d04_postgres import prepared, frozen
from test_ac_integration_postgres import begin, through_canonical
from test_raw_load_postgres import connection


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="D05 acceptance requires migrated PostgreSQL 16 and ARSIA_TEST_DSN",
)


def _deployed(connection):
    signature = connection.execute(
        """SELECT to_regprocedure(
            'published.d05_trend(text,uuid,text,text[],integer,integer,integer[])'
        )"""
    ).fetchone()[0]
    if signature is None:
        pytest.skip("Deploy src/arsia_d05/sql/d05_trend.sql before D05 acceptance")


def _loaded(connection, prepared, frozen):
    _deployed(connection)
    context = begin(connection, prepared, frozen)
    projected = through_canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (2, 3)
    dw_context = replace(context, evidence=context.evidence.for_stage("dw"))
    assert load_dw(ModuleConnection(connection), dw_context)["fact_crash"] == 2
    connection.execute(
        """UPDATE meta.batch
              SET status='succeeded', finished_at=now()
            WHERE batch_id=%s""",
        (context.batch_id,),
    )
    return context


def _one(rows, source, year, month=None):
    return next(
        row for row in rows
        if row["source_id"] == source
        and row["period_year"] == year
        and row["period_month"] == month
    )


def test_s0_year_month_unknown_and_empty_periods(connection, prepared, frozen):
    context = _loaded(connection, prepared, frozen)
    module = ModuleConnection(connection)

    annual = query_trend(
        module, TrendRequest("synthetic", context.batch_id, grain="year")
    )
    assert len(annual) == 15
    nsw = _one(annual, "syn_nsw", 2020)
    assert nsw["coverage_status"] == "covered"
    assert nsw["crash_count"] == 2
    assert nsw["month_known_count"] == 1
    assert nsw["excluded_unknown_month_count"] == 0
    assert nsw["fatal_crash_count"] is not None
    assert nsw["fatality_count"] is not None
    empty = _one(annual, "syn_vic", 2024)
    assert empty["coverage_status"] == "covered"
    assert empty["crash_count"] == 0
    assert empty["fatality_known_count"] == 0
    assert empty["fatality_count"] is None

    monthly = query_trend(
        module,
        TrendRequest(
            "synthetic", context.batch_id, grain="month",
            source_ids=("syn_nsw",), year_from=2020, year_to=2020,
        ),
    )
    assert len(monthly) == 12
    assert sum(row["crash_count"] for row in monthly) == 1
    assert all(row["excluded_unknown_month_count"] == 1 for row in monthly)


def test_year_month_filter_excludes_and_discloses_unknown(connection, prepared, frozen):
    context = _loaded(connection, prepared, frozen)
    rows = query_trend(
        ModuleConnection(connection),
        TrendRequest(
            "synthetic", context.batch_id, grain="year",
            source_ids=("syn_nsw",), year_from=2020, year_to=2020,
            months=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12),
        ),
    )
    assert len(rows) == 1
    assert rows[0]["crash_count"] == 1
    assert rows[0]["excluded_unknown_month_count"] == 1


def test_uncovered_year_returns_nulls(connection, prepared, frozen):
    context = _loaded(connection, prepared, frozen)
    rows = query_trend(
        ModuleConnection(connection),
        TrendRequest(
            "synthetic", context.batch_id, source_ids=("syn_nsw",),
            year_from=2019, year_to=2019,
        ),
    )
    assert len(rows) == 1
    assert rows[0]["coverage_status"] == "not_covered"
    assert rows[0]["crash_count"] is None
    assert rows[0]["fatal_crash_known_count"] is None


def test_unknown_only_measures_keep_crashes_but_return_null_values(
    connection, prepared, frozen
):
    context = _loaded(connection, prepared, frozen)
    connection.execute(
        """UPDATE dw.fact_crash
              SET is_fatal_crash=NULL,
                  fatality_count=NULL,
                  casualty_count=NULL,
                  fatal_crash_eligible=false,
                  fatality_eligible=false,
                  casualty_eligible=false
            WHERE batch_id=%s AND source_id='syn_nsw'""",
        (context.batch_id,),
    )
    rows = query_trend(
        ModuleConnection(connection),
        TrendRequest(
            "synthetic", context.batch_id, source_ids=("syn_nsw",),
            year_from=2020, year_to=2020,
        ),
    )
    assert rows[0]["crash_count"] == 2
    for metric in ("fatal_crash", "fatality", "casualty"):
        assert rows[0][f"{metric}_known_count"] == 0
        assert rows[0][f"{metric}_count"] is None
