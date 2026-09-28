"""D09 acceptance through the real B10 build and E06 publication gate."""

import os

import psycopg
import pytest

if "AC_TEST_RUN" not in os.environ:
    pytest.skip(
        "Use tools/verify_d09_full_build_postgres.py",
        allow_module_level=True,
    )

from arsia_d09 import DashboardFilters, load_dashboard, query_dashboard, resolve_release
from arsia_d09.web import render_page
from test_full_build_postgres import (
    deployed,
    private_database,
    request_factory,
    run,
)


@pytest.fixture(scope="module", autouse=True)
def d09_deployed(deployed):
    """Install the D09 reader function beside the real D05-D08 functions."""

    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        owner.execute("SET LOCAL ROLE arsia_migrator")
        owner.execute(
            open(
                os.path.join(
                    os.path.dirname(__file__),
                    "..",
                    "src",
                    "arsia_d09",
                    "sql",
                    "d09_context.sql",
                ),
                encoding="utf-8",
            ).read()
        )
    return deployed


def _batch_ids(snapshot):
    ids = {
        row["batch_id"]
        for rows in (
            snapshot.sources,
            snapshot.trend,
            snapshot.severity,
            snapshot.map.points,
            snapshot.units,
        )
        for row in rows
    }
    ids.add(snapshot.map.coverage["batch_id"])
    return ids


def test_real_b10_e06_publications_remain_fixed_until_page_refresh(
    request_factory, d09_deployed
):
    """Pin one real release, publish another, then switch only on refresh."""

    first = run(request_factory())
    filters = DashboardFilters("synthetic")

    with psycopg.connect(d09_deployed) as reader:
        assert reader.execute("SELECT current_user").fetchone() == ("arsia_reader",)
        pinned = resolve_release(reader, "synthetic")
        assert str(pinned.batch_id) == first["batch_id"]

        original = query_dashboard(reader, filters, pinned)
        assert _batch_ids(original) == {pinned.batch_id}
        assert sum(row["crash_count"] for row in original.trend) == 6
        assert sum(row["unit_count"] for row in original.units) == 6
        assert str(pinned.batch_id) in render_page(filters, original)

        second = run(
            request_factory(analysis={"year_from": 2021, "year_to": 2024})
        )
        assert second["previous_batch_id"] == first["batch_id"]

        current = resolve_release(reader, "synthetic")
        assert str(current.batch_id) == second["batch_id"]

        still_original = query_dashboard(reader, filters, pinned)
        assert _batch_ids(still_original) == {pinned.batch_id}
        assert still_original == original

        refreshed = load_dashboard(reader, filters)
        assert refreshed.release.batch_id == current.batch_id
        assert _batch_ids(refreshed) == {current.batch_id}
        assert sum(row["crash_count"] for row in refreshed.trend) == 2
        assert str(current.batch_id) in render_page(filters, refreshed)
