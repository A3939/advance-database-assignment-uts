"""Call D08's fixed-batch basic-unit query without changing the connection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

from arsia_ingest.models import IntakeError


QUERY_VERSION = "d08-0.1.0"
_SQL_PATH = Path(__file__).with_name("sql") / "d08_units.sql"
_COLUMNS = (
    "dataset_kind",
    "batch_id",
    "source_id",
    "source_name",
    "jurisdiction_code",
    "statistical_scope",
    "unit_type_code",
    "unit_count",
)

_QUERY_SQL = """
SELECT * FROM published.d08_unit_counts(
    %s::text, %s::uuid, %s::text[], %s::integer, %s::integer, %s::integer[]
)
"""


def install_sql() -> str:
    """Return the versioned SQL deployment unit packaged with D08."""

    return _SQL_PATH.read_text(encoding="utf-8")


def _text_tuple(value: Iterable[str] | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise IntakeError("D08_ARGUMENT", "source_ids must be a sequence of text")
    try:
        result = tuple(value)
    except TypeError as exc:
        raise IntakeError(
            "D08_ARGUMENT", "source_ids must be a sequence of text"
        ) from exc
    if (
        not result
        or any(not isinstance(item, str) or not item.strip() for item in result)
        or len(set(result)) != len(result)
    ):
        raise IntakeError(
            "D08_ARGUMENT", "source_ids must contain unique non-empty text"
        )
    return result


def _month_tuple(value: Iterable[int] | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        raise IntakeError("D08_ARGUMENT", "months must be a sequence of integers")
    try:
        result = tuple(value)
    except TypeError as exc:
        raise IntakeError(
            "D08_ARGUMENT", "months must be a sequence of integers"
        ) from exc
    if (
        not result
        or any(type(item) is not int or not 1 <= item <= 12 for item in result)
        or len(set(result)) != len(result)
    ):
        raise IntakeError(
            "D08_ARGUMENT", "months must contain unique integers from 1 to 12"
        )
    return result


@dataclass(frozen=True)
class UnitRequest:
    """Unit-count filters bound to one successful dataset version."""

    dataset_kind: str
    batch_id: UUID | str
    source_ids: tuple[str, ...] | None = None
    year_from: int | None = None
    year_to: int | None = None
    months: tuple[int, ...] | None = None

    def parameters(self) -> tuple[Any, ...]:
        if self.dataset_kind not in {"official", "synthetic"}:
            raise IntakeError(
                "D08_ARGUMENT", "dataset_kind must be official or synthetic"
            )
        try:
            batch_id = str(UUID(str(self.batch_id)))
        except (TypeError, ValueError, AttributeError) as exc:
            raise IntakeError("D08_ARGUMENT", "batch_id must be a UUID") from exc
        if (
            self.year_from is not None and type(self.year_from) is not int
        ) or (
            self.year_to is not None and type(self.year_to) is not int
        ):
            raise IntakeError("D08_ARGUMENT", "year bounds must be integers")
        if (
            self.year_from is not None
            and self.year_to is not None
            and self.year_from > self.year_to
        ):
            raise IntakeError("D08_ARGUMENT", "year_from must not exceed year_to")
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


def query_units(
    connection: Any, request: UnitRequest
) -> tuple[dict[str, Any], ...]:
    """Return source-scoped eligible unit counts; caller owns transaction."""

    with connection.cursor() as cursor:
        cursor.execute(_QUERY_SQL, request.parameters())
        rows = cursor.fetchall()
    result = []
    for row in rows:
        if len(row) != len(_COLUMNS):
            raise IntakeError(
                "D08_RESULT_SHAPE", "D08 SQL returned an unexpected result shape"
            )
        item = dict(zip(_COLUMNS, row, strict=True))
        if type(item["unit_count"]) is not int or item["unit_count"] < 1:
            raise IntakeError(
                "D08_RESULT_SHAPE", "D08 SQL returned an invalid unit count"
            )
        result.append(item)
    return tuple(result)
