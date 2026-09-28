"""D09 fixed-release page acceptance on PostgreSQL 16."""

from dataclasses import replace
import hashlib
import os
from uuid import UUID, uuid4

import pytest

from arsia_d03 import runner_callback as load_dw
from arsia_d09 import (
    DashboardFilters,
    load_dashboard,
    query_dashboard,
    resolve_release,
)
from arsia_ingest.runner import ModuleConnection
from d_acceptance_support import connection
from test_d04_postgres import prepared, frozen
from test_ac_integration_postgres import begin, through_canonical


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_READER_DSN" not in os.environ,
    reason="D09 acceptance requires PostgreSQL 16 and an arsia_reader DSN",
)


@pytest.fixture
def reader_connection():
    import psycopg

    with psycopg.connect(
        os.environ["ARSIA_TEST_READER_DSN"], autocommit=True, connect_timeout=10
    ) as reader:
        assert reader.info.server_version // 10000 == 16
        assert reader.execute("SELECT current_user").fetchone() == ("arsia_reader",)
        assert reader.execute(
            "SELECT has_schema_privilege(current_user,'dw','USAGE')"
        ).fetchone() == (False,)
        yield reader


def _loaded_and_published(connection, prepared, frozen):
    context = begin(connection, prepared, frozen)
    projected = through_canonical(connection, context)
    assert (len(projected["crash"]), len(projected["unit"])) == (2, 3)
    assert load_dw(
        ModuleConnection(connection), replace(context, evidence=context.evidence.for_stage("dw"))
    )["fact_crash"] == 2
    connection.execute(
        """UPDATE meta.batch SET status='succeeded', finished_at=now()
             WHERE batch_id=%s""",
        (context.batch_id,),
    )
    connection.execute(
        """INSERT INTO meta.current_release(dataset_kind,batch_id)
             VALUES ('synthetic',%s)""",
        (context.batch_id,),
    )
    connection.commit()
    return context


def _cleanup(batches, frozen):
    import psycopg

    value = frozen.as_dict()
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as admin:
        admin.execute("DELETE FROM meta.current_release WHERE batch_id=ANY(%s::uuid[])", (batches,))
        for table in (
            "qa.check_result", "dw.fact_crash", "canonical.unit", "canonical.crash",
            "dw.dim_severity", "dw.dim_source", "rv.link_crash_unit",
            "rv.sat_unit", "rv.sat_crash",
        ):
            admin.execute(
                f"DELETE FROM {table} WHERE batch_id=ANY(%s::uuid[])", (batches,)
            )
        for kind in ("unit", "crash"):
            admin.execute(
                f"DELETE FROM rv.hub_{kind} WHERE first_seen_batch_id=ANY(%s::uuid[])",
                (batches,),
            )
        admin.execute("DELETE FROM meta.batch WHERE batch_id=ANY(%s::uuid[])", (batches,))
        resources = [item["resource_id"] for item in value["files"]]
        admin.execute("DELETE FROM raw.record WHERE resource_id=ANY(%s)", (resources,))
        admin.execute("DELETE FROM meta.resource WHERE resource_id=ANY(%s)", (resources,))
        admin.execute(
            "DELETE FROM meta.source WHERE source_id=ANY(%s)",
            ([item["source_id"] for item in value["sources"]],),
        )
        analysis = value["analysis"]
        admin.execute(
            "DELETE FROM dw.dim_month WHERE calendar_year BETWEEN %s AND %s",
            (analysis["year_from"], analysis["year_to"]),
        )


def test_no_publication_is_explicit(reader_connection):
    from arsia_ingest.models import IntakeError

    with pytest.raises(IntakeError) as error:
        load_dashboard(reader_connection, DashboardFilters("synthetic"))
    assert error.value.code == "D09_NO_PUBLICATION"


def test_reader_loads_all_queries_from_one_real_batch(
    connection, reader_connection, prepared, frozen
):
    context = _loaded_and_published(connection, prepared, frozen)
    batch_id = UUID(context.batch_id)
    try:
        result = load_dashboard(
            reader_connection,
            DashboardFilters("synthetic", source_ids=("syn_nsw",)),
        )

        assert result.release.batch_id == batch_id
        assert {row["batch_id"] for row in result.sources} == {batch_id}
        assert {row["batch_id"] for row in result.trend} == {batch_id}
        assert {row["batch_id"] for row in result.severity} == {batch_id}
        assert {row["batch_id"] for row in result.map.points} == {batch_id}
        assert {row["batch_id"] for row in result.units} == {batch_id}
        assert result.map.coverage["batch_id"] == batch_id
        assert result.map.coverage["crash_count"] == 2
        assert sum(row["unit_count"] for row in result.units) == 3
    finally:
        connection.rollback()
        _cleanup([batch_id], frozen)


def test_pointer_switch_after_pin_does_not_mix_batches(
    connection, reader_connection, prepared, frozen
):
    context = _loaded_and_published(connection, prepared, frozen)
    batch_id = UUID(context.batch_id)
    batches = [batch_id]
    filters = DashboardFilters("synthetic", source_ids=("syn_nsw",))
    pinned = resolve_release(reader_connection, "synthetic")
    second = uuid4()
    batches.append(second)
    try:
        fingerprint = hashlib.sha256(str(second).encode("ascii")).hexdigest()
        connection.execute(
            """INSERT INTO meta.batch(
                   batch_id,dataset_kind,input_fingerprint,manifest,status,finished_at
               ) VALUES (%s,'synthetic',%s,'{}'::jsonb,'succeeded',now())""",
            (second, fingerprint),
        )
        connection.execute(
            """UPDATE meta.current_release
                  SET batch_id=%s,batch_status='succeeded',switched_at=now()
                WHERE dataset_kind='synthetic'""",
            (second,),
        )
        connection.commit()
        result = query_dashboard(reader_connection, filters, pinned)

        assert pinned.batch_id == batch_id
        assert reader_connection.execute(
            "SELECT batch_id FROM published.current_release WHERE dataset_kind='synthetic'"
        ).fetchone() == (second,)
        assert result.release.batch_id == batch_id
        assert result.map.coverage["crash_count"] == 2
        assert all(
            row["batch_id"] == batch_id
            for rows in (result.sources, result.trend, result.severity, result.map.points, result.units)
            for row in rows
        )
    finally:
        connection.rollback()
        _cleanup(batches, frozen)
