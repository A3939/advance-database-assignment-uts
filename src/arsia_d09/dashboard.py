"""Compose D05-D08 without allowing a page read to change batch midway."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from arsia_d05 import TrendRequest, query_trend
from arsia_d06 import SeverityRequest, query_severity
from arsia_d07 import MapRequest, MapResult, query_map
from arsia_d08 import UnitRequest, query_units
from arsia_ingest.models import IntakeError


DASHBOARD_VERSION = "d09-0.1.1"
_RELEASE_SQL = """
SELECT dataset_kind, batch_id, switched_at
FROM published.current_release
WHERE dataset_kind = %s::text
"""
_SOURCE_SQL = """
SELECT * FROM published.d09_batch_sources(%s::text, %s::uuid)
"""
_YEARS_SQL = """
SELECT * FROM published.d09_batch_years(%s::text, %s::uuid)
"""
_SOURCE_COLUMNS = (
    "dataset_kind",
    "batch_id",
    "source_id",
    "source_name",
    "jurisdiction_code",
    "release_label",
    "release_scope",
)


@dataclass(frozen=True)
class DashboardFilters:
    """Page filters shared by every D05-D08 query."""

    dataset_kind: str
    source_ids: tuple[str, ...] | None = None
    year_from: int | None = None
    year_to: int | None = None
    months: tuple[int, ...] | None = None
    trend_grain: str = "year"


@dataclass(frozen=True)
class Release:
    """One publication pointer captured at the start of a page read."""

    dataset_kind: str
    batch_id: UUID
    switched_at: datetime


@dataclass(frozen=True)
class DashboardSnapshot:
    """All dashboard results bound to the same release."""

    release: Release
    filters: DashboardFilters
    sources: tuple[dict[str, Any], ...]
    trend: tuple[dict[str, Any], ...]
    severity: tuple[dict[str, Any], ...]
    map: MapResult
    units: tuple[dict[str, Any], ...]


def _validate_mode(dataset_kind: str) -> None:
    if dataset_kind not in {"official", "synthetic"}:
        raise IntakeError(
            "D09_ARGUMENT", "dataset_kind must be official or synthetic"
        )


def resolve_release(connection: Any, dataset_kind: str) -> Release:
    """Resolve the current successful release exactly once."""

    _validate_mode(dataset_kind)
    with connection.cursor() as cursor:
        cursor.execute(_RELEASE_SQL, (dataset_kind,))
        rows = cursor.fetchall()
    if not rows:
        raise IntakeError(
            "D09_NO_PUBLICATION",
            f"no successful {dataset_kind} release is published",
        )
    if len(rows) != 1 or len(rows[0]) != 3:
        raise IntakeError(
            "D09_RELEASE_SHAPE", "published release returned an invalid shape"
        )
    mode, batch_id, switched_at = rows[0]
    if mode != dataset_kind or not isinstance(batch_id, UUID):
        raise IntakeError(
            "D09_RELEASE_SHAPE", "published release identity is invalid"
        )
    return Release(mode, batch_id, switched_at)


def _sources(connection: Any, release: Release) -> tuple[dict[str, Any], ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            _SOURCE_SQL, (release.dataset_kind, str(release.batch_id))
        )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        if len(row) != len(_SOURCE_COLUMNS):
            raise IntakeError(
                "D09_SOURCE_SHAPE", "D09 source context has an invalid shape"
            )
        result.append(dict(zip(_SOURCE_COLUMNS, row, strict=True)))
    return tuple(result)


def query_dashboard(
    connection: Any,
    filters: DashboardFilters,
    release: Release,
) -> DashboardSnapshot:
    """Run every component against a previously captured release."""

    _validate_mode(filters.dataset_kind)
    if release.dataset_kind != filters.dataset_kind:
        raise IntakeError(
            "D09_RELEASE_MODE", "pinned release belongs to another dataset kind"
        )
    with connection.cursor() as cursor:
        cursor.execute(_YEARS_SQL, (release.dataset_kind, str(release.batch_id)))
        rows = cursor.fetchall()
    if len(rows) != 1 or len(rows[0]) != 2:
        raise IntakeError("D09_YEAR_SHAPE", "D09 year context has an invalid shape")
    lower, upper = rows[0]
    year_from = lower if filters.year_from is None else filters.year_from
    year_to = upper if filters.year_to is None else filters.year_to
    if not lower <= year_from <= year_to <= upper:
        raise IntakeError(
            "D09_YEAR_RANGE",
            f"years must stay within the pinned batch's range: {lower}-{upper}",
        )
    shared = {
        "dataset_kind": filters.dataset_kind,
        "batch_id": release.batch_id,
        "source_ids": filters.source_ids,
        "year_from": year_from,
        "year_to": year_to,
        "months": filters.months,
    }
    sources = _sources(connection, release)
    trend = query_trend(
        connection,
        TrendRequest(grain=filters.trend_grain, **shared),
    )
    severity = query_severity(connection, SeverityRequest(**shared))
    map_result = query_map(connection, MapRequest(**shared))
    units = query_units(connection, UnitRequest(**shared))
    expected = release.batch_id
    for rows in (sources, trend, severity, map_result.points, units):
        if any(row["batch_id"] != expected for row in rows):
            raise IntakeError(
                "D09_BATCH_DRIFT", "a component returned a different batch"
            )
    if map_result.coverage["batch_id"] != expected:
        raise IntakeError(
            "D09_BATCH_DRIFT", "map coverage returned a different batch"
        )
    return DashboardSnapshot(
        release=release,
        filters=filters,
        sources=sources,
        trend=trend,
        severity=severity,
        map=map_result,
        units=units,
    )


def load_dashboard(
    connection: Any, filters: DashboardFilters
) -> DashboardSnapshot:
    """Resolve once at page start, then read all components from that batch."""

    return query_dashboard(
        connection,
        filters,
        resolve_release(connection, filters.dataset_kind),
    )
