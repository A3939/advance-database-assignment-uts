"""D07 acceptance against the real C09 -> D03 PostgreSQL path."""

from dataclasses import replace
from decimal import Decimal
import os

import pytest

from arsia_d03 import runner_callback as load_dw
from arsia_d07 import MapRequest, query_map
from arsia_ingest.runner import ModuleConnection
from d_acceptance_support import connection, fault_injection
from test_d04_postgres import prepared, frozen
from test_ac_integration_postgres import begin, through_canonical


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="D07 acceptance requires migrated PostgreSQL 16 and ARSIA_TEST_DSN",
)


def _deployed(connection):
    for signature in (
        "published.d07_map_points(text,uuid,text[],integer,integer,integer[])",
        "published.d07_map_coverage(text,uuid,text[],integer,integer,integer[])",
    ):
        assert connection.execute(
            "SELECT to_regprocedure(%s)", (signature,)
        ).fetchone()[0]


def _loaded(connection, prepared, frozen, *, succeeded=True):
    _deployed(connection)
    context = begin(connection, prepared, frozen)
    projected = through_canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (2, 3)
    dw_context = replace(context, evidence=context.evidence.for_stage("dw"))
    assert load_dw(ModuleConnection(connection), dw_context)["fact_crash"] == 2
    if succeeded:
        connection.execute(
            """UPDATE meta.batch SET status='succeeded', finished_at=now()
                WHERE batch_id=%s""",
            (context.batch_id,),
        )
    return context


def test_real_nsw_point_count_coverage_identity_and_permissions(
    connection, prepared, frozen
):
    context = _loaded(connection, prepared, frozen)
    result = query_map(
        ModuleConnection(connection),
        MapRequest("synthetic", context.batch_id, source_ids=("syn_nsw",)),
    )

    assert len(result.points) == 1
    assert result.points[0]["source_id"] == "syn_nsw"
    assert result.points[0]["crash_key"]
    assert result.coverage["crash_count"] == 2
    assert result.coverage["point_count"] == 1
    assert result.coverage["coverage_percentage"] == Decimal("50.00")
    assert connection.execute(
        """SELECT has_function_privilege(
            'arsia_reader',
            'published.d07_map_points(text,uuid,text[],integer,integer,integer[])',
            'EXECUTE')"""
    ).fetchone() == (True,)


def test_identical_coordinates_keep_distinct_crash_identities(
    connection, prepared, frozen
):
    context = _loaded(connection, prepared, frozen)
    with fault_injection(connection):
        connection.execute(
            """UPDATE dw.fact_crash
                  SET latitude=-33.1234567, longitude=151.1234567,
                      map_eligible=true
                WHERE batch_id=%s AND source_id='syn_nsw'""",
            (context.batch_id,),
        )
    result = query_map(
        ModuleConnection(connection),
        MapRequest("synthetic", context.batch_id, source_ids=("syn_nsw",)),
    )

    assert len(result.points) == 2
    assert len({row["crash_key"] for row in result.points}) == 2
    assert len({(row["latitude"], row["longitude"]) for row in result.points}) == 1
    assert result.coverage["point_count"] == 2
    assert result.coverage["coverage_percentage"] == Decimal("100.00")


def test_month_filter_and_empty_period_have_exact_denominators(
    connection, prepared, frozen
):
    context = _loaded(connection, prepared, frozen)
    january = query_map(
        ModuleConnection(connection),
        MapRequest(
            "synthetic", context.batch_id, source_ids=("syn_nsw",),
            year_from=2020, year_to=2020, months=(1,),
        ),
    )
    assert len(january.points) == 1
    assert january.coverage["crash_count"] == 1
    assert january.coverage["coverage_percentage"] == Decimal("100.00")

    empty = query_map(
        ModuleConnection(connection),
        MapRequest("synthetic", context.batch_id, year_from=2024, year_to=2024),
    )
    assert empty.points == ()
    assert empty.coverage["crash_count"] == 0
    assert empty.coverage["point_count"] == 0
    assert empty.coverage["coverage_percentage"] is None


def test_running_batch_is_rejected(connection, prepared, frozen):
    import psycopg

    context = _loaded(connection, prepared, frozen, succeeded=False)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="D07_BATCH_STATUS"):
        query_map(
            ModuleConnection(connection), MapRequest("synthetic", context.batch_id)
        )


def test_wrong_mode_is_rejected(connection, prepared, frozen):
    import psycopg

    context = _loaded(connection, prepared, frozen)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="D07_BATCH_MODE"):
        query_map(
            ModuleConnection(connection), MapRequest("official", context.batch_id)
        )


def test_unknown_source_is_rejected(connection, prepared, frozen):
    import psycopg

    context = _loaded(connection, prepared, frozen)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="D07_SOURCE"):
        query_map(
            ModuleConnection(connection),
            MapRequest("synthetic", context.batch_id, source_ids=("not-enabled",)),
        )
