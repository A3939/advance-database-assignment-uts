"""D09 acceptance through the real B10 build and E06 publication gate."""

import os
from importlib.resources import files
from http.server import ThreadingHTTPServer
import threading
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import uuid4

import pytest

if "AC_TEST_RUN" not in os.environ:
    pytest.skip(
        "Use tools/verify_d09_full_build_postgres.py",
        allow_module_level=True,
    )

import psycopg

from arsia_d09 import DashboardFilters, load_dashboard, query_dashboard, resolve_release
from arsia_d09.web import make_handler, render_page
from arsia_d05 import TrendRequest, query_trend
from arsia_ingest.models import IntakeError
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
            files("arsia_d09").joinpath("sql/d09_context.sql").read_text(encoding="utf-8")
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
        assert reader.execute(
            "SELECT * FROM published.d09_batch_years(%s, %s)",
            ("synthetic", pinned.batch_id),
        ).fetchone() == (2020, 2024)
        assert reader.execute(
            "SELECT * FROM published.d09_batch_years(%s, %s)",
            ("synthetic", current.batch_id),
        ).fetchone() == (2021, 2024)
        old_year = DashboardFilters("synthetic", year_from=2020, year_to=2020)
        assert query_dashboard(reader, old_year, pinned).release == pinned
        with pytest.raises(IntakeError, match="2021-2024"):
            query_dashboard(reader, old_year, current)

        refreshed = load_dashboard(reader, filters)
        assert refreshed.release.batch_id == current.batch_id
        assert _batch_ids(refreshed) == {current.batch_id}
        assert sum(row["crash_count"] for row in refreshed.trend) == 2
        assert str(current.batch_id) in render_page(filters, refreshed)


@pytest.fixture
def http_url(d09_deployed):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(d09_deployed, False))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("query,code", [
    ("sources=not_in_manifest", "D05_SOURCE"),
    ("year_from=2019", "D09_YEAR_RANGE"),
    ("year_to=2025", "D09_YEAR_RANGE"),
    ("year_from=2025", "D09_YEAR_RANGE"),
    ("year_to=2019", "D09_YEAR_RANGE"),
    ("months=13", "D09_ARGUMENT"),
])
def test_real_http_filters_return_readable_400_and_next_request_works(request_factory, http_url, query, code):
    result = run(request_factory())
    with pytest.raises(HTTPError) as error:
        urlopen(http_url + "?" + query, timeout=10)
    assert error.value.code == 400
    body = error.value.read().decode("utf-8")
    assert code in body and 'class="state error"' in body
    with urlopen(http_url, timeout=10) as response:
        assert response.status == 200
        assert result["batch_id"] in response.read().decode("utf-8")


@pytest.mark.parametrize("years", [(None, None), (2020, None), (None, 2024), (2020, 2024), (2022, 2022)])
def test_manifest_defaults_and_inclusive_year_boundaries(request_factory, d09_deployed, years):
    run(request_factory())
    with psycopg.connect(d09_deployed) as reader:
        filters = DashboardFilters("synthetic", year_from=years[0], year_to=years[1])
        snapshot = load_dashboard(reader, filters)
        assert {row["period_year"] for row in snapshot.trend} == set(
            range(years[0] or 2020, (years[1] or 2024) + 1)
        )
        # D05 still supports uncovered periods outside D09's page range.
        outside = query_trend(reader, TrendRequest(
            "synthetic", snapshot.release.batch_id, year_from=2019, year_to=2019,
        ))
        assert outside and all(row["coverage_status"] == "not_covered" for row in outside)


def test_real_http_renders_sql_counts_without_replacing_nulls(request_factory, d09_deployed, http_url):
    run(request_factory())
    with psycopg.connect(d09_deployed) as reader:
        snapshot = load_dashboard(reader, DashboardFilters("synthetic"))
    with urlopen(http_url, timeout=10) as response:
        page = response.read().decode("utf-8")
    fields = (
        "crash_count", "month_known_count", "excluded_unknown_month_count",
        "fatal_crash_count", "fatal_crash_known_count", "fatality_count",
        "fatality_known_count", "casualty_count", "casualty_known_count",
    )
    for name in fields:
        assert f"<th>{name.replace('_', ' ').title()}</th>" in page
    assert any(row[name] is None for row in snapshot.trend for name in fields)
    assert any(row[name] == 0 for row in snapshot.trend for name in fields)
    for row in snapshot.trend:
        expected = "".join(
            '<td><span class="null">NULL</span></td>' if row[name] is None
            else f"<td>{row[name]}</td>" for name in fields
        )
        assert expected in page


def test_year_helper_checks_batch_identity_status_and_reader_permissions(request_factory, d09_deployed):
    result = run(request_factory())
    unfinished = uuid4()
    with psycopg.connect(os.environ["ARSIA_TEST_DSN"]) as loader:
        loader.execute(
            """INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest,status)
               VALUES (%s,'synthetic',%s,'{}'::jsonb,'running')""",
            (unfinished, unfinished.hex * 2),
        )
        assert loader.execute(
            "SELECT * FROM published.d09_batch_years(%s,%s)",
            ("synthetic", result["batch_id"]),
        ).fetchone() == (2020, 2024)
    with psycopg.connect(d09_deployed, autocommit=True) as reader:
        for kind, batch, message in (
            ("bad", result["batch_id"], "D09_DATASET_KIND"),
            ("official", result["batch_id"], "D09_BATCH_MODE"),
            ("synthetic", uuid4(), "D09_BATCH:"),
            ("synthetic", unfinished, "D09_BATCH_STATUS"),
        ):
            with pytest.raises(psycopg.errors.InvalidParameterValue, match=message):
                reader.execute("SELECT * FROM published.d09_batch_years(%s,%s)", (kind, batch))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute("SELECT manifest FROM meta.batch")
        properties = reader.execute(
            """SELECT proowner::regrole::text, prosecdef, proconfig,
                      NOT EXISTS (SELECT 1 FROM aclexplode(proacl) WHERE grantee=0)
                 FROM pg_proc
                WHERE oid='published.d09_batch_years(text,uuid)'::regprocedure"""
        ).fetchone()
        assert properties == ("arsia_migrator", True, ["search_path=pg_catalog"], True)


def test_unexpected_database_error_returns_500_without_internal_details(request_factory, http_url):
    run(request_factory())
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        owner.execute("REVOKE EXECUTE ON FUNCTION published.d09_batch_years(text,uuid) FROM arsia_reader")
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(http_url, timeout=10)
        assert error.value.code == 500
        page = error.value.read().decode("utf-8")
        assert "D09_DATABASE" in page
        assert "permission denied" not in page and "d09_batch_years" not in page
    finally:
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
            owner.execute("GRANT EXECUTE ON FUNCTION published.d09_batch_years(text,uuid) TO arsia_reader")
