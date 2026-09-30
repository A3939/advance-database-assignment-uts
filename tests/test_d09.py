"""D09 composition, renderer and local HTTP tests."""

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from http.server import ThreadingHTTPServer
import importlib
from importlib.resources import files
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import urlopen
from uuid import UUID

import pytest

import arsia_d09.dashboard as dashboard
from arsia_d07 import MapResult
from arsia_d09 import DashboardFilters, Release, load_dashboard, query_dashboard
from arsia_d09.web import demo_snapshot, make_handler, parse_filters, render_page
from arsia_ingest.models import IntakeError


BATCH = UUID("12345678-1234-5678-9234-567812345678")
NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, parameters):
        self.connection.calls.append((sql, parameters))
        self.rows = self.connection.results.pop(0)

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def cursor(self):
        return Cursor(self)


def source():
    return (
        "synthetic", BATCH, "syn_nsw", "Synthetic <NSW>", "NSW",
        "s0-v1", "s0-nsw-v1",
    )


def _component_rows(batch_id=BATCH):
    trend = ({"batch_id": batch_id, "source_id": "syn_nsw"},)
    severity = ({"batch_id": batch_id, "source_id": "syn_nsw"},)
    points = ({"batch_id": batch_id, "source_id": "syn_nsw"},)
    coverage = {
        "batch_id": batch_id,
        "crash_count": 2,
        "point_count": 1,
        "coverage_percentage": Decimal("50.00"),
    }
    units = ({"batch_id": batch_id, "source_id": "syn_nsw", "unit_count": 3},)
    return trend, severity, MapResult(points, coverage), units


def test_page_resolves_release_once_and_passes_one_batch(monkeypatch):
    connection = Connection(((("synthetic", BATCH, NOW),), ((2020, 2024),), (source(),)))
    seen = []
    trend, severity, map_result, units = _component_rows()

    def capture(value):
        def call(connection, request):
            seen.append(request)
            return value
        return call

    monkeypatch.setattr(dashboard, "query_trend", capture(trend))
    monkeypatch.setattr(dashboard, "query_severity", capture(severity))
    monkeypatch.setattr(dashboard, "query_map", capture(map_result))
    monkeypatch.setattr(dashboard, "query_units", capture(units))
    filters = DashboardFilters(
        "synthetic", source_ids=("syn_nsw",), year_from=2020, year_to=2024,
        months=(1, 2), trend_grain="month",
    )

    result = load_dashboard(connection, filters)

    assert result.release.batch_id == BATCH
    assert sum("published.current_release" in sql for sql, _ in connection.calls) == 1
    assert len(seen) == 4
    assert {request.batch_id for request in seen} == {BATCH}
    assert all(request.source_ids == ("syn_nsw",) for request in seen)
    assert seen[0].grain == "month"
    assert all((request.year_from, request.year_to) == (2020, 2024) for request in seen)


@pytest.mark.parametrize("year_from,year_to", [(2019, None), (None, 2025), (2025, None), (None, 2019)])
def test_page_rejects_years_outside_pinned_manifest_before_component_queries(year_from, year_to):
    connection = Connection((((2020, 2024),),))
    with pytest.raises(IntakeError, match="2020-2024") as error:
        query_dashboard(
            connection, DashboardFilters("synthetic", year_from=year_from, year_to=year_to),
            Release("synthetic", BATCH, NOW),
        )
    assert error.value.code == "D09_YEAR_RANGE"
    assert len(connection.calls) == 1


def test_no_publication_and_release_mode_mismatch():
    with pytest.raises(IntakeError) as error:
        load_dashboard(Connection(((),)), DashboardFilters("synthetic"))
    assert error.value.code == "D09_NO_PUBLICATION"

    release = Release("official", BATCH, NOW)
    with pytest.raises(IntakeError) as error:
        query_dashboard(Connection(()), DashboardFilters("synthetic"), release)
    assert error.value.code == "D09_RELEASE_MODE"


@pytest.mark.parametrize(
    "query",
    [
        "mode=wrong",
        "mode=synthetic&mode=official",
        "sources=a,,b",
        "sources=a,a",
        "months=0",
        "months=1,1",
        "months=x",
        "year_from=2024&year_to=2020",
        "grain=week",
        "unknown=x",
    ],
)
def test_invalid_page_arguments(query):
    with pytest.raises(IntakeError) as error:
        parse_filters(query)
    assert error.value.code == "D09_ARGUMENT"


def test_renderer_preserves_null_zero_and_escapes_source_text():
    filters = DashboardFilters("synthetic")
    snapshot = demo_snapshot(filters)
    source_row = dict(snapshot.sources[0])
    source_row["source_name"] = "<unsafe>"
    coverage = dict(snapshot.map.coverage)
    coverage["coverage_percentage"] = None
    changed = dashboard.DashboardSnapshot(
        snapshot.release,
        filters,
        (source_row,),
        snapshot.trend,
        snapshot.severity,
        MapResult(snapshot.map.points, coverage),
        (),
    )

    page = render_page(filters, changed)

    assert "&lt;unsafe&gt;" in page and "<unsafe>" not in page
    assert '<span class="null">NULL</span>' in page
    assert "Eligible units</span><strong>0</strong>" in page
    assert str(snapshot.release.batch_id) in page
    assert "browser-side recalculation" in page


def test_demo_http_page_and_bad_request():
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(None, True))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with urlopen(f"http://127.0.0.1:{server.server_port}/", timeout=5) as response:
            page = response.read().decode("utf-8")
            assert response.status == 200
            assert "Fixed example mode" in page
            assert "00000000-0000-4000-8000-000000000009" in page
        with pytest.raises(HTTPError) as error:
            urlopen(
                f"http://127.0.0.1:{server.server_port}/?months=13", timeout=5
            )
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_d09_sql_contract_and_packaged_assets():
    root = Path(__file__).resolve().parents[1]
    package = files("arsia_d09")
    for path in ("sql/d09_context.sql", "templates/dashboard.html", "static/dashboard.css"):
        assert package.joinpath(path).read_bytes() == (root / "src/arsia_d09" / path).read_bytes()
    sql = " ".join(package.joinpath("sql/d09_context.sql").read_text(encoding="utf-8").lower().split())
    assert "d09-0.1.1" in sql
    assert "security definer" in sql
    assert "set search_path = pg_catalog" in sql
    assert "candidate.status" in sql and "succeeded" in sql
    assert "from dw.dim_source as source" in sql
    assert "source.batch_id = p_batch_id" in sql
    assert "to arsia_reader, arsia_loader" in sql
    assert "commit" not in sql and "rollback" not in sql
    assert (root / "src/arsia_d09/templates/dashboard.html").is_file()
    assert (root / "src/arsia_d09/static/dashboard.css").is_file()


def test_renderer_keeps_outcome_known_counts_and_unknown_month_context():
    snapshot = demo_snapshot(DashboardFilters("synthetic"))
    row = snapshot.trend[0]
    row.update(
        month_known_count=41, excluded_unknown_month_count=43,
        fatal_crash_count=0, fatal_crash_known_count=47,
        fatality_count=None, fatality_known_count=0,
        casualty_count=53, casualty_known_count=59,
    )
    page = render_page(snapshot.filters, snapshot)
    for label in (
        "Month Known Count", "Excluded Unknown Month Count", "Fatal Crash Count",
        "Fatal Crash Known Count", "Fatality Known Count", "Casualty Known Count",
    ):
        assert f"<th>{label}</th>" in page
    assert (
        '<td>41</td><td>43</td><td>0</td><td>47</td>'
        '<td><span class="null">NULL</span></td><td>0</td><td>53</td><td>59</td>'
    ) in page


def test_rendered_error_escapes_sql_message():
    page = render_page(
        DashboardFilters("synthetic"),
        error=IntakeError("D09_ARGUMENT", "Invalid source <script>alert(1)</script>"),
    )
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>" not in page


def test_d09_inventory_hashes_and_status_boundary():
    root = Path(__file__).resolve().parents[1]
    inventory = json.loads(
        (root / "config/d09-inventory.json").read_text(encoding="utf-8")
    )
    assert inventory["implementation_complete"] is True
    assert inventory["real_publication_acceptance_complete"] is True
    assert inventory["complete_d09"] is True
    evidence = root / inventory["acceptance"]["evidence"] / "summary.json"
    summary = json.loads(evidence.read_text(encoding="utf-8"))
    assert summary["exit_code"] == 0
    assert summary["tests"] == 17
    assert summary["skipped"] == 0
    assert summary["d09_real_publication_acceptance"] is True
    assert summary["pointer_switch_verified"] is True
    declared = {item["path"]: item["sha256"] for item in inventory["code_files"]}
    assert set(declared) == set(inventory["components"]["dashboard"])
    for path, expected in declared.items():
        data = (root / path).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == expected
    module_name, callback_name = inventory["binding"]["python"].split(":")
    callback = getattr(importlib.import_module(module_name), callback_name)
    assert callback is load_dashboard
