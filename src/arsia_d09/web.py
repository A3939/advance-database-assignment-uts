"""Small server-rendered D09 page; no separate JSON API or auth layer."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from arsia_d07 import MapResult
from arsia_ingest.models import IntakeError

from .dashboard import DashboardFilters, DashboardSnapshot, Release, load_dashboard


_ROOT = Path(__file__).resolve().parent
_TEMPLATE = _ROOT / "templates" / "dashboard.html"
_CSS = _ROOT / "static" / "dashboard.css"


def _single(values: dict[str, list[str]], name: str, default: str = "") -> str:
    found = values.get(name, [])
    if len(found) > 1:
        raise IntakeError("D09_ARGUMENT", f"{name} must appear once")
    return found[0].strip() if found else default


def _csv_text(value: str) -> tuple[str, ...] | None:
    if not value:
        return None
    result = tuple(part.strip() for part in value.split(","))
    if any(not part for part in result) or len(set(result)) != len(result):
        raise IntakeError(
            "D09_ARGUMENT", "sources must be unique comma-separated values"
        )
    return result


def _csv_months(value: str) -> tuple[int, ...] | None:
    if not value:
        return None
    try:
        result = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise IntakeError("D09_ARGUMENT", "months must be integers") from exc
    if (
        any(month < 1 or month > 12 for month in result)
        or len(set(result)) != len(result)
    ):
        raise IntakeError(
            "D09_ARGUMENT", "months must be unique values from 1 to 12"
        )
    return result


def _year(value: str, name: str) -> int | None:
    if not value:
        return None
    try:
        year = int(value)
    except ValueError as exc:
        raise IntakeError("D09_ARGUMENT", f"{name} must be an integer") from exc
    if not 1 <= year <= 9999:
        raise IntakeError("D09_ARGUMENT", f"{name} is outside 1-9999")
    return year


def parse_filters(query: str) -> DashboardFilters:
    """Parse the page query string without silently accepting bad values."""

    values = parse_qs(query, keep_blank_values=True)
    allowed = {"mode", "sources", "year_from", "year_to", "months", "grain"}
    unknown = set(values) - allowed
    if unknown:
        raise IntakeError(
            "D09_ARGUMENT", "unknown page parameter", parameters=sorted(unknown)
        )
    filters = DashboardFilters(
        dataset_kind=_single(values, "mode", "synthetic"),
        source_ids=_csv_text(_single(values, "sources")),
        year_from=_year(_single(values, "year_from"), "year_from"),
        year_to=_year(_single(values, "year_to"), "year_to"),
        months=_csv_months(_single(values, "months")),
        trend_grain=_single(values, "grain", "year"),
    )
    if filters.dataset_kind not in {"official", "synthetic"}:
        raise IntakeError("D09_ARGUMENT", "mode must be official or synthetic")
    if filters.trend_grain not in {"year", "month"}:
        raise IntakeError("D09_ARGUMENT", "grain must be year or month")
    if (
        filters.year_from is not None
        and filters.year_to is not None
        and filters.year_from > filters.year_to
    ):
        raise IntakeError("D09_ARGUMENT", "year_from must not exceed year_to")
    return filters


def _text(value: object) -> str:
    if value is None:
        return '<span class="null">NULL</span>'
    if isinstance(value, (tuple, list)):
        return escape(", ".join(str(item) for item in value))
    return escape(str(value))


def _table(title: str, rows: tuple[dict[str, object], ...], columns: tuple[str, ...]) -> str:
    if not rows:
        return (
            f'<section class="panel"><h2>{escape(title)}</h2>'
            '<p class="empty">No rows for the pinned batch and filters.</p></section>'
        )
    head = "".join(f"<th>{escape(column.replace('_', ' ').title())}</th>" for column in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_text(row.get(column))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    return (
        f'<section class="panel"><h2>{escape(title)}</h2><div class="table-wrap">'
        f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
        "</div></section>"
    )


def _filter_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, tuple):
        return ",".join(str(item) for item in value)
    return str(value)


def render_page(
    filters: DashboardFilters,
    snapshot: DashboardSnapshot | None = None,
    error: IntakeError | None = None,
    *,
    demo: bool = False,
) -> str:
    """Render SQL values directly, preserving NULL and zero."""

    template = _TEMPLATE.read_text(encoding="utf-8")
    css = _CSS.read_text(encoding="utf-8")
    values = {
        "mode": filters.dataset_kind,
        "sources": _filter_value(filters.source_ids),
        "year_from": _filter_value(filters.year_from),
        "year_to": _filter_value(filters.year_to),
        "months": _filter_value(filters.months),
        "grain": filters.trend_grain,
    }
    fields = {name: escape(value, quote=True) for name, value in values.items()}
    fields["official_selected"] = "selected" if filters.dataset_kind == "official" else ""
    fields["synthetic_selected"] = "selected" if filters.dataset_kind == "synthetic" else ""
    fields["year_selected"] = "selected" if filters.trend_grain == "year" else ""
    fields["month_selected"] = "selected" if filters.trend_grain == "month" else ""
    fields["demo_banner"] = (
        '<div class="banner">Fixed example mode: values are illustrative.</div>'
        if demo else ""
    )
    if error is not None:
        message = escape(str(error))
        fields["summary"] = (
            f'<section class="state error"><strong>{escape(error.code)}</strong>'
            f"<p>{message}</p></section>"
        )
        fields["content"] = ""
    elif snapshot is None:
        fields["summary"] = '<section class="state"><p>No dashboard read.</p></section>'
        fields["content"] = ""
    else:
        coverage = snapshot.map.coverage
        unit_total = sum(row["unit_count"] for row in snapshot.units)
        percentage = coverage["coverage_percentage"]
        fields["summary"] = f"""
        <section class="release-strip">
          <div><span>Mode</span><strong>{escape(snapshot.release.dataset_kind)}</strong></div>
          <div><span>Pinned batch</span><strong class="mono">{snapshot.release.batch_id}</strong></div>
          <div><span>Pointer time</span><strong>{escape(snapshot.release.switched_at.isoformat())}</strong></div>
        </section>
        <section class="metrics">
          <article><span>Crashes</span><strong>{_text(coverage['crash_count'])}</strong></article>
          <article><span>Map points</span><strong>{_text(coverage['point_count'])}</strong></article>
          <article><span>Map coverage</span><strong>{_text(percentage)}{'' if percentage is None else '%'}</strong></article>
          <article><span>Eligible units</span><strong>{unit_total}</strong></article>
        </section>
        """
        source_cards = "".join(
            "<article>"
            f"<strong>{_text(row['source_name'])}</strong>"
            f"<span>{_text(row['jurisdiction_code'])} · {_text(row['release_label'])}</span>"
            f"<small>{_text(row['source_id'])}</small>"
            "</article>"
            for row in snapshot.sources
        ) or '<p class="empty">No sources in this batch.</p>'
        sections = [
            f'<section class="panel"><h2>Frozen source releases</h2><div class="source-grid">{source_cards}</div></section>',
            _table(
                "Trend",
                snapshot.trend,
                ("source_id", "grain", "period_year", "period_month", "coverage_status", "crash_count", "fatality_count", "casualty_count"),
            ),
            _table(
                "Severity",
                snapshot.severity,
                ("source_id", "severity_code", "severity_label", "definition_version", "crash_count"),
            ),
            _table(
                "Map points",
                snapshot.map.points,
                ("source_id", "crash_key", "occurrence_year", "occurrence_month", "severity_code", "latitude", "longitude"),
            ),
            _table(
                "Basic units",
                snapshot.units,
                ("source_id", "statistical_scope", "unit_type_code", "unit_count"),
            ),
        ]
        fields["content"] = "".join(sections)
    fields["css"] = css
    for name, value in fields.items():
        template = template.replace("{{" + name + "}}", str(value))
    return template


def demo_snapshot(filters: DashboardFilters) -> DashboardSnapshot:
    """Clearly labelled fixed response for UI work without a database."""

    batch = UUID("00000000-0000-4000-8000-000000000009")
    release = Release(filters.dataset_kind, batch, datetime(2026, 1, 1, tzinfo=timezone.utc))
    source = {
        "dataset_kind": filters.dataset_kind,
        "batch_id": batch,
        "source_id": "demo_nsw",
        "source_name": "Fixed example NSW",
        "jurisdiction_code": "NSW",
        "release_label": "demo-only",
        "release_scope": "demo-v1",
    }
    trend = ({"batch_id": batch, "source_id": "demo_nsw", "grain": "year", "period_year": 2020, "period_month": None, "coverage_status": "complete", "crash_count": 2, "fatality_count": 1, "casualty_count": 3},)
    severity = ({"batch_id": batch, "source_id": "demo_nsw", "severity_code": "F", "severity_label": "Fatal", "definition_version": "demo-v1", "crash_count": 1},)
    point = {"batch_id": batch, "source_id": "demo_nsw", "crash_key": "demo-crash-1", "occurrence_year": 2020, "occurrence_month": 1, "severity_code": "F", "latitude": Decimal("-33.1"), "longitude": Decimal("151.2")}
    coverage = {"batch_id": batch, "crash_count": 2, "point_count": 1, "coverage_percentage": Decimal("50.00")}
    units = ({"batch_id": batch, "source_id": "demo_nsw", "statistical_scope": "demo_traffic_unit", "unit_type_code": "CAR", "unit_count": 3},)
    return DashboardSnapshot(release, filters, (source,), trend, severity, MapResult((point,), coverage), units)


def make_handler(dsn: str | None, demo: bool):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib hook
            target = urlsplit(self.path)
            if target.path != "/":
                self.send_error(404)
                return
            try:
                filters = parse_filters(target.query)
                if demo:
                    snapshot = demo_snapshot(filters)
                else:
                    if not dsn:
                        raise IntakeError(
                            "D09_CONFIGURATION", "ARSIA_READER_DSN is required"
                        )
                    import psycopg
                    with psycopg.connect(dsn, autocommit=True) as connection:
                        snapshot = load_dashboard(connection, filters)
                page = render_page(filters, snapshot, demo=demo)
                status = 200
            except IntakeError as exc:
                filters = locals().get("filters", DashboardFilters("synthetic"))
                page = render_page(filters, error=exc, demo=demo)
                status = 200 if exc.code == "D09_NO_PUBLICATION" else 400
            data = page.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dsn", default=os.environ.get("ARSIA_READER_DSN"))
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if not args.demo and not args.dsn:
        parser.error("set ARSIA_READER_DSN or use --demo")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.dsn, args.demo))
    print(f"D09 dashboard: http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
