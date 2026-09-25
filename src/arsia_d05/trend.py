"""Call D05's fixed-batch L5 trend query without changing the connection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from arsia_ingest.models import IntakeError


QUERY_VERSION = "d05-0.1.0"
_SQL_PATH = Path(__file__).with_name("sql") / "d05_trend.sql"
_COLUMNS = (
    "dataset_kind",
    "batch_id",
    "source_id",
    "grain",
    "period_year",
    "period_month",
    "coverage_status",
    "requested_month_count",
    "covered_month_count",
    "coverage_basis",
    "crash_count",
    "month_known_count",
    "excluded_unknown_month_count",
    "fatal_crash_count",
    "fatal_crash_known_count",
    "fatality_count",
    "fatality_known_count",
    "casualty_count",
    "casualty_known_count",
)

QUERY_SQL = """
SELECT *
FROM published.d05_trend(
    %s::text,
    %s::uuid,
    %s::text,
    %s::text[],
    %s::integer,
    %s::integer,
    %s::integer[]
)
"""


def install_sql() -> str:
    """Return the versioned SQL deployment unit packaged with D05."""

    return _SQL_PATH.read_text(encoding="utf-8")


def _text_tuple(name: str, value: Iterable[str] | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise IntakeError("D05_ARGUMENT", f"{name} must be a sequence of text values")
    try:
        result = tuple(value)
    except TypeError as exc:
        raise IntakeError(
            "D05_ARGUMENT", f"{name} must be a sequence of text values"
        ) from exc
    if (not result or any(not isinstance(item, str) or not item.strip()
                          for item in result) or len(set(result)) != len(result)):
        raise IntakeError("D05_ARGUMENT", f"{name} must contain unique non-empty text")
    return result


def _month_tuple(value: Iterable[int] | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise IntakeError("D05_ARGUMENT", "months must be a sequence of integers")
    try:
        result = tuple(value)
    except TypeError as exc:
        raise IntakeError(
            "D05_ARGUMENT", "months must be a sequence of integers"
        ) from exc
    if (not result or any(type(item) is not int or not 1 <= item <= 12
                          for item in result) or len(set(result)) != len(result)):
        raise IntakeError(
            "D05_ARGUMENT", "months must contain unique integers from 1 to 12"
        )
    return result


@dataclass(frozen=True)
class TrendRequest:
    """L5 arguments bound to one successful dataset version."""

    dataset_kind: str
    batch_id: UUID | str
    grain: str = "year"
    source_ids: tuple[str, ...] | None = None
    year_from: int | None = None
    year_to: int | None = None
    months: tuple[int, ...] | None = None

    def parameters(self) -> tuple[Any, ...]:
        if self.dataset_kind not in {"official", "synthetic"}:
            raise IntakeError(
                "D05_ARGUMENT", "dataset_kind must be official or synthetic"
            )
        try:
            batch_id = str(UUID(str(self.batch_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise IntakeError("D05_ARGUMENT", "batch_id must be a UUID") from exc
        if self.grain not in {"year", "month"}:
            raise IntakeError("D05_ARGUMENT", "grain must be year or month")
        if ((self.year_from is not None and type(self.year_from) is not int)
                or (self.year_to is not None and type(self.year_to) is not int)):
            raise IntakeError("D05_ARGUMENT", "year bounds must be integers")
        if (self.year_from is not None and self.year_to is not None
                and self.year_from > self.year_to):
            raise IntakeError("D05_ARGUMENT", "year_from must not exceed year_to")
        sources = _text_tuple("source_ids", self.source_ids)
        months = _month_tuple(self.months)
        return (
            self.dataset_kind,
            batch_id,
            self.grain,
            list(sources) if sources is not None else None,
            self.year_from,
            self.year_to,
            list(months) if months is not None else None,
        )


def query_trend(connection: Any, request: TrendRequest) -> tuple[dict[str, Any], ...]:
    """Return D05 rows; transaction and connection ownership stay with caller."""

    parameters = request.parameters()
    with connection.cursor() as cursor:
        cursor.execute(QUERY_SQL, parameters)
        rows = cursor.fetchall()
    result = []
    for row in rows:
        if len(row) != len(_COLUMNS):
            raise IntakeError(
                "D05_QUERY_SHAPE", "D05 SQL returned an unexpected result shape"
            )
        result.append(dict(zip(_COLUMNS, row, strict=True)))
    return tuple(result)
