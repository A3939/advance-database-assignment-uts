"""Load D03 crash facts from the selected batch's Canonical crashes.

The module copies the fact fields from ``canonical.crash`` without reading
Raw, Vault or Unit rows.  It owns no connection lifecycle: B10 keeps the
commit, rollback, close and publication responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from arsia_d02 import runner_callback as d02_runner_callback


FACT_INSERT_SQL = """
INSERT INTO dw.fact_crash (
    batch_id,
    source_id,
    release_scope,
    crash_key,
    occurrence_year,
    month_id,
    severity_code,
    is_fatal_crash,
    fatality_count,
    casualty_count,
    fatal_crash_eligible,
    fatality_eligible,
    casualty_eligible,
    latitude,
    longitude,
    map_eligible
)
SELECT
    batch_id,
    source_id,
    release_scope,
    crash_key,
    occurrence_year,
    CASE
        WHEN occurrence_month IS NULL THEN NULL
        ELSE occurrence_year * 100 + occurrence_month
    END,
    severity_code,
    is_fatal_crash,
    fatality_count,
    casualty_count,
    fatal_crash_eligible,
    fatality_eligible,
    casualty_eligible,
    latitude,
    longitude,
    map_eligible
FROM canonical.crash
WHERE batch_id = %s::uuid
ON CONFLICT (batch_id, source_id, release_scope, crash_key) DO NOTHING
"""


PREFLIGHT_SQL = """
SELECT
    count(*) FILTER (WHERE source.source_id IS NULL),
    count(*) FILTER (
        WHERE source.source_id IS NOT NULL
          AND source.release_scope IS DISTINCT FROM crash.release_scope
    ),
    count(*) FILTER (WHERE severity.severity_code IS NULL),
    count(*) FILTER (
        WHERE severity.severity_code IS NOT NULL
          AND severity.definition_version
              IS DISTINCT FROM crash.severity_definition_version
    ),
    count(*) FILTER (
        WHERE crash.occurrence_month IS NOT NULL
          AND month.month_id IS NULL
    )
FROM canonical.crash AS crash
LEFT JOIN dw.dim_source AS source
  ON source.batch_id = crash.batch_id
 AND source.source_id = crash.source_id
LEFT JOIN dw.dim_severity AS severity
  ON severity.batch_id = crash.batch_id
 AND severity.source_id = crash.source_id
 AND severity.severity_code = crash.severity_code
LEFT JOIN dw.dim_month AS month
  ON month.calendar_year = crash.occurrence_year
 AND month.calendar_month = crash.occurrence_month
WHERE crash.batch_id = %s::uuid
"""


VERIFY_SQL = """
WITH expected AS (
    SELECT
        batch_id,
        source_id,
        release_scope,
        crash_key,
        occurrence_year,
        CASE
            WHEN occurrence_month IS NULL THEN NULL
            ELSE occurrence_year * 100 + occurrence_month
        END AS month_id,
        severity_code,
        is_fatal_crash,
        fatality_count,
        casualty_count,
        fatal_crash_eligible,
        fatality_eligible,
        casualty_eligible,
        latitude,
        longitude,
        map_eligible
    FROM canonical.crash
    WHERE batch_id = %s::uuid
), differences AS (
    SELECT 1
    FROM expected
    FULL OUTER JOIN dw.fact_crash AS fact
      USING (batch_id, source_id, release_scope, crash_key)
    WHERE COALESCE(expected.batch_id, fact.batch_id) = %s::uuid
      AND (
          expected.batch_id IS NULL
          OR fact.batch_id IS NULL
          OR fact.occurrence_year IS DISTINCT FROM expected.occurrence_year
          OR fact.month_id IS DISTINCT FROM expected.month_id
          OR fact.severity_code IS DISTINCT FROM expected.severity_code
          OR fact.is_fatal_crash IS DISTINCT FROM expected.is_fatal_crash
          OR fact.fatality_count IS DISTINCT FROM expected.fatality_count
          OR fact.casualty_count IS DISTINCT FROM expected.casualty_count
          OR fact.fatal_crash_eligible
              IS DISTINCT FROM expected.fatal_crash_eligible
          OR fact.fatality_eligible
              IS DISTINCT FROM expected.fatality_eligible
          OR fact.casualty_eligible
              IS DISTINCT FROM expected.casualty_eligible
          OR fact.latitude IS DISTINCT FROM expected.latitude
          OR fact.longitude IS DISTINCT FROM expected.longitude
          OR fact.map_eligible IS DISTINCT FROM expected.map_eligible
      )
)
SELECT
    (SELECT count(*) FROM expected),
    (SELECT count(*) FROM dw.fact_crash WHERE batch_id = %s::uuid),
    (SELECT count(*) FROM differences)
"""


SOURCE_COUNTS_SQL = """
SELECT source_id, count(*)
FROM dw.fact_crash
WHERE batch_id = %s::uuid
GROUP BY source_id
ORDER BY source_id
"""


class FactContractError(ValueError):
    """Canonical crashes and D02 dimensions cannot safely define D03 facts."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True)
class FactLoadResult:
    """Verified D03 result for one candidate batch."""

    fact_count: int
    inserted_count: int
    source_counts: dict[str, int]

    def counts(self) -> dict[str, int]:
        return {"fact_crash": self.fact_count}


def _batch_id(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FactContractError(
            "D03_BATCH_ID", "batch_id must be a UUID", actual=str(value)
        ) from exc


def _preflight(connection: Any, batch_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(PREFLIGHT_SQL, (batch_id,))
        row = cursor.fetchone()

    if row is None or len(row) != 5:
        raise FactContractError(
            "D03_PREFLIGHT_SHAPE",
            "dimension preflight returned an unexpected result shape",
        )

    names = (
        "missing_source",
        "release_scope_mismatch",
        "missing_severity",
        "severity_definition_mismatch",
        "missing_month",
    )
    failures = {name: int(value) for name, value in zip(names, row) if value}
    if failures:
        raise FactContractError(
            "D03_DIMENSION_CONTRACT",
            "Canonical crashes do not match the loaded D02 dimensions",
            failures=failures,
        )


def _verify(connection: Any, batch_id: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(VERIFY_SQL, (batch_id, batch_id, batch_id))
        row = cursor.fetchone()

    if row is None or len(row) != 3:
        raise FactContractError(
            "D03_VERIFY_SHAPE",
            "fact reconciliation returned an unexpected result shape",
        )

    canonical_count, fact_count, difference_count = map(int, row)
    if canonical_count != fact_count or difference_count:
        raise FactContractError(
            "D03_DATABASE_MISMATCH",
            "fact_crash does not exactly match the selected Canonical crashes",
            canonical_count=canonical_count,
            fact_count=fact_count,
            difference_count=difference_count,
        )
    return canonical_count


def _source_counts(connection: Any, batch_id: str) -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute(SOURCE_COUNTS_SQL, (batch_id,))
        return {str(source_id): int(count) for source_id, count in cursor.fetchall()}


def load_facts(connection: Any, batch_id: Any) -> FactLoadResult:
    """Load and exactly reconcile one fact for every Canonical crash."""

    batch = _batch_id(batch_id)
    _preflight(connection, batch)

    with connection.cursor() as cursor:
        cursor.execute(FACT_INSERT_SQL, (batch,))
        inserted_count = max(int(cursor.rowcount), 0)

    fact_count = _verify(connection, batch)
    return FactLoadResult(
        fact_count=fact_count,
        inserted_count=inserted_count,
        source_counts=_source_counts(connection, batch),
    )


def runner_callback(connection: Any, context: Any) -> dict[str, int]:
    """Combined D02 + D03 DW callback on B10's caller-owned transaction."""

    dimension_counts = d02_runner_callback(connection, context)
    try:
        result = load_facts(connection, context.batch_id)
    except FactContractError as exc:
        from arsia_ingest.models import IntakeError

        raise IntakeError(exc.code, str(exc), **exc.details) from exc

    evidence = getattr(context, "evidence", None)
    if evidence is not None:
        evidence.write_json(
            "d03-fact-crash.json",
            {
                "batch_id": str(context.batch_id),
                "fact_count": result.fact_count,
                "inserted_count": result.inserted_count,
                "source_counts": result.source_counts,
                "canonical_reconciled": True,
                "unit_rows_joined": False,
            },
        )

    return {**dimension_counts, **result.counts()}
