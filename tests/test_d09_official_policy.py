"""D09 uses the official reader policy instead of presenting unavailable zeros."""
from dataclasses import replace
from decimal import Decimal
from http.server import ThreadingHTTPServer
import threading
from urllib.request import urlopen

import pytest

import arsia_d09.dashboard as dashboard
from arsia_d07 import MapResult
from arsia_d09 import DashboardFilters, Release, load_dashboard, query_dashboard
from arsia_d09.web import demo_snapshot, make_handler, render_page
from arsia_ingest import official_reader
from arsia_ingest.models import IntakeError
from test_d09 import BATCH, NOW, Connection


@pytest.mark.parametrize("sources", (None, (), ("official_nsw", "official_vic"), "official_nsw"))
def test_official_needs_one_source_before_database_access(sources):
    filters = DashboardFilters("official", source_ids=sources)
    with pytest.raises(IntakeError) as error:
        load_dashboard(object(), filters)
    assert error.value.code == "D09_OFFICIAL_SOURCE"
    with pytest.raises(IntakeError) as error:
        query_dashboard(object(), filters, Release("official", BATCH, NOW))
    assert error.value.code == "D09_OFFICIAL_SOURCE"


def official_snapshot(monkeypatch, source):
    calls = []
    trend = ({"batch_id": BATCH, "source_id": source, "crash_count": 5,
              "coverage_basis": "pinned coverage", "fatality_count": None},)
    severity = ({"batch_id": BATCH, "source_id": source, "crash_count": 5},)
    points = ({"batch_id": BATCH, "source_id": source, "crash_key": "hidden-map-row",
               "latitude": Decimal("-31.5"), "longitude": Decimal("150.25")},)
    coverage = {"batch_id": BATCH, "crash_count": 5, "point_count": 2,
                "coverage_percentage": Decimal("40.00")}
    units = ({"batch_id": BATCH, "source_id": source, "unit_type_code": "hidden-unit-row", "unit_count": 9},)

    def capture(value):
        def query(connection, request):
            calls.append(request)
            return value
        return query

    monkeypatch.setattr(dashboard, "query_trend", capture(trend))
    monkeypatch.setattr(dashboard, "query_severity", capture(severity))
    monkeypatch.setattr(dashboard, "query_map", capture(MapResult(points, coverage)))
    monkeypatch.setattr(dashboard, "query_units", capture(units))
    # Keep query_official itself real, including its source and availability rules.
    monkeypatch.setattr(official_reader, "query_trend", capture(trend))
    monkeypatch.setattr(official_reader, "query_units", capture(units))
    sources = tuple(("official", BATCH, sid, sid + " release", sid[-3:].upper(), "pinned", "reviewed")
                    for sid in ("official_nsw", "official_vic", "official_qld"))
    connection = Connection((((2020, 2024),), sources))
    filters = DashboardFilters("official", source_ids=(source,), months=(1, 2))
    result = query_dashboard(connection, filters, Release("official", BATCH, NOW))
    return result, calls


@pytest.mark.parametrize("source", ("official_nsw", "official_vic", "official_qld"))
def test_official_snapshot_preserves_sql_values_and_attaches_real_policy(monkeypatch, source):
    snapshot, calls = official_snapshot(monkeypatch, source)
    assert snapshot.map.coverage["coverage_percentage"] == Decimal("40.00")
    assert snapshot.map.points[0]["crash_key"] == "hidden-map-row"
    assert snapshot.units[0]["unit_count"] == 9
    assert len(snapshot.sources) == 1 and snapshot.sources[0]["source_id"] == source
    assert all(request.source_ids == (source,) and request.batch_id == BATCH for request in calls)
    assert all((request.year_from, request.year_to, request.months) == (2020, 2024, (1, 2)) for request in calls)
    assert snapshot.official_reports["map"]["status"] == "unavailable"
    assert snapshot.official_reports["units"]["status"] == ("available" if source == "official_nsw" else "unavailable")
    assert snapshot.official_reports["map"]["quality_limits"]


@pytest.mark.parametrize("source", ("official_nsw", "official_vic", "official_qld"))
def test_official_renderer_explains_unavailable_outputs(monkeypatch, source):
    snapshot, _ = official_snapshot(monkeypatch, source)
    page = render_page(snapshot.filters, snapshot)
    assert "Crashes</span><strong>5</strong>" in page
    assert "Map points</span><strong>Unavailable</strong>" in page
    assert "Map coverage</span><strong>Unavailable</strong>" in page
    assert "hidden-map-row" not in page and "40.00%" not in page
    assert snapshot.official_reports["map"]["reason"] in page
    assert "interstate totals are not supported" in page
    assert dashboard.DASHBOARD_VERSION in page and "{{version}}" not in page
    if source == "official_nsw":
        assert "Eligible units</span><strong>9</strong>" in page
        assert "hidden-unit-row" in page
    else:
        assert "Eligible units</span><strong>Unavailable</strong>" in page
        assert "hidden-unit-row" not in page
        assert snapshot.official_reports["units"]["reason"] in page


def test_unknown_official_source_is_rejected_by_shared_policy(monkeypatch):
    with pytest.raises(IntakeError) as error:
        official_snapshot(monkeypatch, "<unknown>")
    assert error.value.code == "OFFICIAL_READER"


def test_policy_and_error_text_is_escaped(monkeypatch):
    snapshot, _ = official_snapshot(monkeypatch, "official_vic")
    reports = {key: dict(value) for key, value in snapshot.official_reports.items()}
    reports["map"].update(reason="<script>map</script>", source_label="<source>",
                          quality_limits=["<limit>"], comparison_scope="<scope>")
    reports["units"]["reason"] = "<script>unit</script>"
    page = render_page(snapshot.filters, replace(snapshot, official_reports=reports))
    assert "<script>" not in page and "<source>" not in page
    for escaped in ("&lt;script&gt;map&lt;/script&gt;", "&lt;script&gt;unit&lt;/script&gt;",
                    "&lt;source&gt;", "&lt;limit&gt;", "&lt;scope&gt;"):
        assert escaped in page
    error = render_page(snapshot.filters, error=IntakeError("D09_OFFICIAL_SOURCE", "<bad-source>"))
    assert "&lt;bad-source&gt;" in error and "<bad-source>" not in error


def test_official_snapshot_without_policy_does_not_render_numbers(monkeypatch):
    snapshot, _ = official_snapshot(monkeypatch, "official_vic")
    page = render_page(snapshot.filters, replace(snapshot, official_reports=None))
    assert "D09_OFFICIAL_CONTEXT" in page
    assert "Crashes</span>" not in page and "hidden-map-row" not in page


def test_official_demo_http_keeps_the_labelled_example():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(None, True))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/?mode=official&sources=official_nsw"
        with urlopen(url, timeout=5) as response:
            page = response.read().decode("utf-8")
            assert response.status == 200
        assert "D09_OFFICIAL_CONTEXT" not in page
        assert "Fixed example mode: values are illustrative." in page
        assert "Fixed example NSW" in page and "demo-only" in page
        assert "Mode</span><strong>official</strong>" in page
        assert "Crashes</span><strong>2</strong>" in page
        assert "Map coverage</span><strong>50.00%</strong>" in page
        assert "demo-crash-1" in page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_synthetic_values_and_default_snapshot_interface_are_unchanged():
    snapshot = demo_snapshot(DashboardFilters("synthetic"))
    assert snapshot.official_reports is None
    page = render_page(snapshot.filters, snapshot)
    assert "Map coverage</span><strong>50.00%</strong>" in page
    assert "Eligible units</span><strong>3</strong>" in page
    assert "demo-crash-1" in page and "Unavailable" not in page
