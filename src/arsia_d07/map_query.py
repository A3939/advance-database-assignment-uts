"""Call D07's fixed-batch map queries without changing the connection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from arsia_ingest.models import IntakeError


QUERY_VERSION = "d07-0.1.0"
_SQL_PATH = Path(__file__).with_name("sql") / "d07_map.sql"
_POINT_COLUMNS = (
    "dataset_kind",
    "batch_id",
    "source_id",
    "source_name",
    "jurisdiction_code",
    "release_scope",
    "crash_key",
    "occurrence_year",
    "occurrence_month",
    "severity_code",
    "latitude",
    "longitude",
)
_COVERAGE_COLUMNS = (
    "dataset_kind",
    "batch_id",
    "filter_source_ids",
    "filter_year_from",
    "filter_year_to",
    "filter_months",
    "crash_count",
    "point_count",
    "coverage_percentage",
)

_POINT_SQL = """
SELECT * FROM published.d07_map_points(
    %s::text, %s::uuid, %s::text[], %s::integer, %s::integer, %s::integer[]
)
"""
_COVERAGE_SQL = """
SELECT * FROM published.d07_map_coverage(
    %s::text, %s::uuid, %s::text[], %s::integer, %s::integer, %s::integer[]
)
"""


def install_sql() -> str:
    """Return the versioned SQL deployment unit packaged with D07."""

    return _SQL_PATH.read_text(encoding="utf-8")


def _text_tuple(value: Iterable[str] | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise IntakeError("D07_ARGUMENT", "source_ids must be a sequence of text")
    try:
        result = tuple(value)
    except TypeError as exc:
        raise IntakeError(
            "D07_ARGUMENT", "source_ids must be a sequence of text"
        ) from exc
    if (
        not result
        or any(not isinstance(item, str) or not item.strip() for item in result)
        or len(set(result)) != len(result)
    ):
        raise IntakeError(
            "D07_ARGUMENT", "source_ids must contain unique non-empty text"
        )
    return result


def _month_tuple(value: Iterable[int] | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise IntakeError("D07_ARGUMENT", "months must be a sequence of integers")
    try:
        result = tuple(value)
    except TypeError as exc:
        raise IntakeError(
            "D07_ARGUMENT", "months must be a sequence of integers"
        ) from exc
    if (
        not result
        or any(type(item) is not int or not 1 <= item <= 12 for item in result)
        or len(set(result)) != len(result)
    ):
        raise IntakeError(
            "D07_ARGUMENT", "months must contain unique integers from 1 to 12"
        )
    return result


@dataclass(frozen=True)
class MapRequest:
    """Map filters bound to one successful dataset version."""

    dataset_kind: str
    batch_id: UUID | str
    source_ids: tuple[str, ...] | None = None
    year_from: int | None = None
    year_to: int | None = None
    months: tuple[int, ...] | None = None

    def parameters(self) -> tuple[Any, ...]:
        if self.dataset_kind not in {"official", "synthetic"}:
            raise IntakeError(
                "D07_ARGUMENT", "dataset_kind must be official or synthetic"
            )
        try:
            batch_id = str(UUID(str(self.batch_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise IntakeError("D07_ARGUMENT", "batch_id must be a UUID") from exc
        if (
            self.year_from is not None and type(self.year_from) is not int
        ) or (
            self.year_to is not None and type(self.year_to) is not int
        ):
            raise IntakeError("D07_ARGUMENT", "year bounds must be integers")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise IntakeError("D07_ARGUMENT", "year_from must not exceed year_to")
        sources = _text_tuple(self.source_ids)
        months = _month_tuple(self.months)
        return (
            self.dataset_kind,
            batch_id,
            list(sources) if sources is not None else None,
            self.year_from,
            self.year_to,
            list(months) if months is not None else None,
        )


@dataclass(frozen=True)
class MapResult:
    """Eligible points and SQL-calculated coverage for identical filters."""

    points: tuple[dict[str, Any], ...]
    coverage: dict[str, Any]


def _rows(cursor: Any, columns: tuple[str, ...], code: str):
    result = []
    for row in cursor.fetchall():
        if len(row) != len(columns):
            raise IntakeError(code, "D07 SQL returned an unexpected result shape")
        result.append(dict(zip(columns, row, strict=True)))
    return result


def query_map(connection: Any, request: MapRequest) -> MapResult:
    """Return eligible crash identities and coverage; caller owns transaction."""

    parameters = request.parameters()
    with connection.cursor() as cursor:
        cursor.execute(_POINT_SQL, parameters)
        points = tuple(_rows(cursor, _POINT_COLUMNS, "D07_POINT_SHAPE"))
        cursor.execute(_COVERAGE_SQL, parameters)
        coverage_rows = _rows(cursor, _COVERAGE_COLUMNS, "D07_COVERAGE_SHAPE")
    if len(coverage_rows) != 1:
        raise IntakeError(
            "D07_COVERAGE_SHAPE", "D07 coverage query must return exactly one row"
        )
    coverage = coverage_rows[0]
    if coverage["point_count"] != len(points):
        raise IntakeError(
            "D07_RECONCILIATION", "D07 point rows differ from SQL point count"
        )
    return MapResult(points=points, coverage=coverage)
