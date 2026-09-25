"""D08 acceptance against the real C09 -> D03 PostgreSQL path."""

from dataclasses import replace
import os

import pytest

from arsia_d03 import runner_callback as load_dw
from arsia_d08 import UnitRequest, query_units
from arsia_ingest.runner import ModuleConnection
from d_acceptance_support import connection, fault_injection
from test_d04_postgres import prepared, frozen
from test_ac_integration_postgres import begin, through_canonical


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="D08 acceptance requires migrated PostgreSQL 16 and ARSIA_TEST_DSN",
)


def _deployed(connection):
    signature = (
        "published.d08_unit_counts(text,uuid,text[],integer,integer,integer[])"
    )
    assert connection.execute("SELECT to_regprocedure(%s)", (signature,)).fetchone()[0]


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


def test_real_nsw_units_scope_type_count_and_permissions(
    connection, prepared, frozen
):
    context = _loaded(connection, prepared, frozen)
    rows = query_units(
        ModuleConnection(connection),
        UnitRequest("synthetic", context.batch_id, source_ids=("syn_nsw",)),
    )

    assert sum(row["unit_count"] for row in rows) == 3
    assert {row["source_id"] for row in rows} == {"syn_nsw"}
    assert {row["statistical_scope"] for row in rows} == {
        "synthetic_traffic_unit"
    }
    assert {row["unit_type_code"] for row in rows} == {"CAR"}
    assert connection.execute(
        """SELECT has_function_privilege(
            'arsia_reader',
            'published.d08_unit_counts(text,uuid,text[],integer,integer,integer[])',
            'EXECUTE')"""
    ).fetchone() == (True,)


def test_ineligible_unit_is_excluded_without_changing_crash_facts(
    connection, prepared, frozen
):
    context = _loaded(connection, prepared, frozen)
    before = connection.execute(
        "SELECT count(*) FROM dw.fact_crash WHERE batch_id=%s",
        (context.batch_id,),
    ).fetchone()[0]
    with fault_injection(connection):
        connection.execute(
            """UPDATE canonical.unit SET count_eligible=false
                 WHERE ctid IN (
                    SELECT ctid FROM canonical.unit
                     WHERE batch_id=%s ORDER BY unit_key LIMIT 1
                 )""",
            (context.batch_id,),
        )
    rows = query_units(
        ModuleConnection(connection), UnitRequest("synthetic", context.batch_id)
    )
    assert sum(row["unit_count"] for row in rows) == 2
    assert connection.execute(
        "SELECT count(*) FROM dw.fact_crash WHERE batch_id=%s",
        (context.batch_id,),
    ).fetchone()[0] == before == 2


def test_parent_time_filters_and_empty_result(connection, prepared, frozen):
    context = _loaded(connection, prepared, frozen)
    parent = connection.execute(
        """SELECT occurrence_year, month_id %% 100, count(*)
             FROM dw.fact_crash AS fact
             JOIN canonical.unit AS unit
               ON unit.batch_id=fact.batch_id
              AND unit.source_id=fact.source_id
              AND unit.release_scope=fact.release_scope
              AND unit.crash_key=fact.crash_key
            WHERE fact.batch_id=%s AND unit.count_eligible
            GROUP BY occurrence_year, month_id %% 100
            ORDER BY count(*) DESC, occurrence_year, month_id %% 100
            LIMIT 1""",
        (context.batch_id,),
    ).fetchone()
    selected = query_units(
        ModuleConnection(connection),
        UnitRequest(
            "synthetic",
            context.batch_id,
            year_from=parent[0],
            year_to=parent[0],
            months=(parent[1],),
        ),
    )
    assert sum(row["unit_count"] for row in selected) == parent[2]

    empty = query_units(
        ModuleConnection(connection),
        UnitRequest("synthetic", context.batch_id, year_from=2024, year_to=2024),
    )
    assert empty == ()


def test_running_batch_is_rejected(connection, prepared, frozen):
    import psycopg

    context = _loaded(connection, prepared, frozen, succeeded=False)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="D08_BATCH_STATUS"):
        query_units(
            ModuleConnection(connection), UnitRequest("synthetic", context.batch_id)
        )


def test_wrong_mode_is_rejected(connection, prepared, frozen):
    import psycopg

    context = _loaded(connection, prepared, frozen)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="D08_BATCH_MODE"):
        query_units(
            ModuleConnection(connection), UnitRequest("official", context.batch_id)
        )


def test_unknown_source_is_rejected(connection, prepared, frozen):
    import psycopg

    context = _loaded(connection, prepared, frozen)
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="D08_SOURCE"):
        query_units(
            ModuleConnection(connection),
            UnitRequest("synthetic", context.batch_id, source_ids=("not-enabled",)),
        )
