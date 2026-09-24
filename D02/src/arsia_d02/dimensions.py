"""Build and load the three D02 dimensions from a frozen manifest.

The module owns no connection lifecycle.  In particular, it never commits,
rolls back, closes the connection, or changes session settings.  B10's runner
keeps those responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
from uuid import UUID


SOURCE_INSERT = """
INSERT INTO dw.dim_source (
    batch_id, source_id, source_name, jurisdiction_code,
    release_label, release_scope
) VALUES (%s::uuid, %s, %s, %s, %s, %s)
ON CONFLICT (batch_id, source_id) DO NOTHING
"""

MONTH_INSERT = """
INSERT INTO dw.dim_month (month_id, calendar_year, calendar_month)
VALUES (%s, %s, %s)
ON CONFLICT (month_id) DO NOTHING
"""

SEVERITY_INSERT = """
INSERT INTO dw.dim_severity (
    batch_id, source_id, severity_code, severity_label,
    definition_version, definition_text
) VALUES (%s::uuid, %s, %s, %s, %s, %s)
ON CONFLICT (batch_id, source_id, severity_code) DO NOTHING
"""


class DimensionContractError(ValueError):
    """The supplied manifest cannot safely define the D02 dimensions."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class DimensionRows:
    """Validated rows in database column order."""

    sources: tuple[tuple[Any, ...], ...]
    months: tuple[tuple[int, int, int], ...]
    severities: tuple[tuple[Any, ...], ...]

    def counts(self) -> dict[str, int]:
        return {
            "dim_source": len(self.sources),
            "dim_month": len(self.months),
            "dim_severity": len(self.severities),
        }


def _fail(code: str, message: str, **details: Any) -> None:
    raise DimensionContractError(code, message, **details)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("D02_MANIFEST_SHAPE", f"{name} must be an object", field=name)
    return value


def _list(value: Any, name: str) -> Sequence[Any]:
    if not isinstance(value, list):
        _fail("D02_MANIFEST_SHAPE", f"{name} must be a list", field=name)
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("D02_MANIFEST_VALUE", f"{name} must be nonempty text", field=name)
    return value


def _year(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("D02_ANALYSIS_YEAR", f"{name} must be an integer", field=name)
    return value


def _batch_id(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise DimensionContractError(
            "D02_BATCH_ID", "batch_id must be a UUID", actual=str(value)
        ) from exc


def _severity_entries(manifest: Mapping[str, Any]) -> Sequence[Any]:
    # Frozen manifests place severity under rules.  B's s0_definitions() output
    # exposes the same entries at the top level for fixture development.
    rules = manifest.get("rules")
    if rules is not None:
        return _list(_mapping(rules, "rules").get("severity"), "rules.severity")
    return _list(manifest.get("severity"), "severity")


def build_dimension_rows(manifest: Mapping[str, Any], batch_id: Any) -> DimensionRows:
    """Validate manifest definitions and create deterministic D02 rows."""

    manifest = _mapping(manifest, "manifest")
    batch = _batch_id(batch_id)
    source_values = _list(manifest.get("sources"), "sources")
    if not source_values:
        _fail("D02_SOURCES_EMPTY", "sources must contain at least one source")

    sources: list[tuple[Any, ...]] = []
    source_ids: set[str] = set()
    for position, raw in enumerate(source_values):
        source = _mapping(raw, f"sources[{position}]")
        source_id = _text(source.get("source_id"), f"sources[{position}].source_id")
        if source_id in source_ids:
            _fail("D02_SOURCE_DUPLICATE", "source_id is duplicated", source_id=source_id)
        source_ids.add(source_id)
        sources.append(
            (
                batch,
                source_id,
                _text(source.get("source_name"), f"sources[{position}].source_name"),
                _text(source.get("jurisdiction_code"), f"sources[{position}].jurisdiction_code"),
                _text(source.get("release_label"), f"sources[{position}].release_label"),
                _text(source.get("release_scope"), f"sources[{position}].release_scope"),
            )
        )

    analysis = _mapping(manifest.get("analysis"), "analysis")
    year_from = _year(analysis.get("year_from"), "analysis.year_from")
    year_to = _year(analysis.get("year_to"), "analysis.year_to")
    if year_from > year_to:
        _fail(
            "D02_ANALYSIS_RANGE",
            "analysis.year_from must not exceed analysis.year_to",
            year_from=year_from,
            year_to=year_to,
        )
    months = [
        (year * 100 + month, year, month)
        for year in range(year_from, year_to + 1)
        for month in range(1, 13)
    ]

    severities: list[tuple[Any, ...]] = []
    severity_keys: set[tuple[str, str]] = set()
    missing_sources: set[str] = set()
    for position, raw in enumerate(_severity_entries(manifest)):
        severity = _mapping(raw, f"severity[{position}]")
        source_id = _text(severity.get("source_id"), f"severity[{position}].source_id")
        if source_id not in source_ids:
            _fail(
                "D02_SEVERITY_SOURCE",
                "severity refers to a source absent from the manifest",
                source_id=source_id,
            )
        code = _text(severity.get("severity_code"), f"severity[{position}].severity_code")
        key = (source_id, code)
        if key in severity_keys:
            _fail(
                "D02_SEVERITY_DUPLICATE",
                "a source severity code has more than one definition",
                source_id=source_id,
                severity_code=code,
            )
        severity_keys.add(key)
        if code == "__MISSING__":
            missing_sources.add(source_id)
        fatal = severity.get("is_fatal_crash")
        if fatal is not None and not isinstance(fatal, bool):
            _fail(
                "D02_SEVERITY_FATAL_FLAG",
                "is_fatal_crash must be true, false or null",
                source_id=source_id,
                severity_code=code,
            )
        severities.append(
            (
                batch,
                source_id,
                code,
                _text(severity.get("severity_label"), f"severity[{position}].severity_label"),
                _text(severity.get("definition_version"), f"severity[{position}].definition_version"),
                _text(severity.get("definition_text"), f"severity[{position}].definition_text"),
            )
        )

    without_missing = sorted(source_ids - missing_sources)
    if without_missing:
        _fail(
            "D02_MISSING_CATEGORY",
            "every source must define the explicit __MISSING__ severity category",
            source_ids=without_missing,
        )

    return DimensionRows(
        sources=tuple(sorted(sources, key=lambda row: row[1])),
        months=tuple(months),
        severities=tuple(sorted(severities, key=lambda row: (row[1], row[2]))),
    )


def _normalise_batch_rows(rows: Sequence[Sequence[Any]]) -> tuple[tuple[Any, ...], ...]:
    return tuple((str(row[0]), *row[1:]) for row in rows)


def _verify(connection: Any, batch_id: str, rows: DimensionRows) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT batch_id, source_id, source_name, jurisdiction_code,
                      release_label, release_scope
                 FROM dw.dim_source
                WHERE batch_id = %s::uuid
                ORDER BY source_id""",
            (batch_id,),
        )
        actual_sources = _normalise_batch_rows(cursor.fetchall())
        cursor.execute(
            """SELECT month_id, calendar_year, calendar_month
                 FROM dw.dim_month
                WHERE calendar_year BETWEEN %s AND %s
                ORDER BY calendar_year, calendar_month""",
            (rows.months[0][1], rows.months[-1][1]),
        )
        actual_months = tuple(tuple(row) for row in cursor.fetchall())
        cursor.execute(
            """SELECT batch_id, source_id, severity_code, severity_label,
                      definition_version, definition_text
                 FROM dw.dim_severity
                WHERE batch_id = %s::uuid
                ORDER BY source_id, severity_code""",
            (batch_id,),
        )
        actual_severities = _normalise_batch_rows(cursor.fetchall())

    expected = (rows.sources, rows.months, rows.severities)
    actual = (actual_sources, actual_months, actual_severities)
    if actual != expected:
        names = ("dim_source", "dim_month", "dim_severity")
        differences = {
            name: {"expected": len(want), "actual": len(got)}
            for name, want, got in zip(names, expected, actual)
            if want != got
        }
        _fail(
            "D02_DATABASE_MISMATCH",
            "database dimension rows differ from the frozen manifest",
            differences=differences,
        )


def load_dimensions(connection: Any, batch_id: Any, manifest: Mapping[str, Any]) -> dict[str, int]:
    """Load D02 rows on the caller's transaction and verify exact contents."""

    rows = build_dimension_rows(manifest, batch_id)
    with connection.cursor() as cursor:
        cursor.executemany(SOURCE_INSERT, rows.sources)
        cursor.executemany(MONTH_INSERT, rows.months)
        cursor.executemany(SEVERITY_INSERT, rows.severities)
    _verify(connection, str(rows.sources[0][0]), rows)
    return rows.counts()


def runner_callback(connection: Any, context: Any) -> dict[str, int]:
    """B10 module callback for the D02-only integration stage."""

    try:
        manifest = context.manifest.as_dict()
        counts = load_dimensions(connection, context.batch_id, manifest)
    except DimensionContractError as exc:
        try:
            from arsia_ingest.models import IntakeError
        except ImportError:
            raise
        raise IntakeError(exc.code, str(exc), **exc.details) from exc

    evidence = getattr(context, "evidence", None)
    if evidence is not None:
        evidence.write_json(
            "d02-dimensions.json",
            {"batch_id": str(context.batch_id), "counts": counts},
        )
    return counts
