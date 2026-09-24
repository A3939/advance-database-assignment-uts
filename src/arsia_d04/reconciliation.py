"""Reconcile Canonical crashes with D03 facts for QA06.

The check creates one result for every enabled source and configured year,
including empty years.  It compares complete crash identities before totals,
uses NULL-safe field comparisons, validates Canonical lineage and frozen
dimension definitions, and persists results on B's caller-owned transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping
from uuid import UUID

from arsia_ingest.models import IntakeError
from arsia_ingest.qa_input import QAReport, write_results


RULE_ID = "QA06_RECONCILIATION"
PRODUCER_VERSION = "d04-0.1.0"
METRIC_NAMES = (
    "missing_fact_count",
    "extra_fact_count",
    "field_mismatch_count",
    "lineage_error_count",
    "definition_error_count",
    "crash_delta",
    "fatal_crash_delta",
    "fatality_delta",
    "casualty_delta",
    "fatal_crash_known_delta",
    "fatality_known_delta",
    "casualty_known_delta",
)


_CTES = """
WITH allowed_lineage AS (
    SELECT *
    FROM jsonb_to_recordset(%s::jsonb) AS allowed(
        lineage_kind text,
        resource_id text,
        file_sha256 text,
        parser_version text
    )
), canonical_rows AS (
    SELECT
        crash.*,
        primary_raw.resource_id AS primary_resource_id,
        primary_raw.file_sha256 AS primary_file_sha256,
        primary_raw.parser_version AS primary_parser_version,
        primary_raw.row_locator AS primary_row_locator,
        location_raw.resource_id AS location_resource_id,
        location_raw.file_sha256 AS location_file_sha256,
        location_raw.parser_version AS location_parser_version,
        location_raw.row_locator AS location_row_locator,
        (
            primary_raw.raw_record_id IS NULL
            OR NOT EXISTS (
                SELECT 1
                FROM allowed_lineage AS allowed
                WHERE allowed.lineage_kind = 'primary'
                  AND allowed.resource_id = primary_raw.resource_id
                  AND allowed.file_sha256 = primary_raw.file_sha256
                  AND allowed.parser_version = primary_raw.parser_version
            )
            OR (
                crash.location_record_id IS NOT NULL
                AND (
                    location_raw.raw_record_id IS NULL
                    OR NOT EXISTS (
                        SELECT 1
                        FROM allowed_lineage AS allowed
                        WHERE allowed.lineage_kind = 'location'
                          AND allowed.resource_id = location_raw.resource_id
                          AND allowed.file_sha256 = location_raw.file_sha256
                          AND allowed.parser_version = location_raw.parser_version
                    )
                )
            )
            OR (crash.map_eligible AND crash.location_record_id IS NULL)
        ) AS lineage_error,
        (
            source.source_id IS NULL
            OR source.release_scope IS DISTINCT FROM crash.release_scope
            OR severity.severity_code IS NULL
            OR severity.definition_version
                IS DISTINCT FROM crash.severity_definition_version
        ) AS definition_error
    FROM canonical.crash AS crash
    LEFT JOIN raw.record AS primary_raw
      ON primary_raw.raw_record_id = crash.raw_record_id
     AND primary_raw.source_id = crash.source_id
    LEFT JOIN raw.record AS location_raw
      ON location_raw.raw_record_id = crash.location_record_id
     AND location_raw.source_id = crash.source_id
    LEFT JOIN dw.dim_source AS source
      ON source.batch_id = crash.batch_id
     AND source.source_id = crash.source_id
    LEFT JOIN dw.dim_severity AS severity
      ON severity.batch_id = crash.batch_id
     AND severity.source_id = crash.source_id
     AND severity.severity_code = crash.severity_code
    WHERE crash.batch_id = %s::uuid
      AND crash.source_id = %s
      AND crash.occurrence_year = %s
), fact_rows AS (
    SELECT *
    FROM dw.fact_crash
    WHERE batch_id = %s::uuid
      AND source_id = %s
      AND occurrence_year = %s
), paired AS (
    SELECT
        canonical_rows AS canonical_row,
        fact_rows AS fact_row,
        canonical_rows.batch_id IS NOT NULL AS has_canonical,
        fact_rows.batch_id IS NOT NULL AS has_fact,
        canonical_rows.lineage_error,
        canonical_rows.definition_error,
        canonical_rows.primary_resource_id,
        canonical_rows.primary_file_sha256,
        canonical_rows.primary_parser_version,
        canonical_rows.primary_row_locator,
        canonical_rows.location_resource_id,
        canonical_rows.location_file_sha256,
        canonical_rows.location_parser_version,
        canonical_rows.location_row_locator,
        COALESCE(canonical_rows.release_scope, fact_rows.release_scope)
            AS release_scope,
        COALESCE(canonical_rows.crash_key, fact_rows.crash_key) AS crash_key,
        (
            canonical_rows.batch_id IS NOT NULL
            AND fact_rows.batch_id IS NOT NULL
            AND (
                fact_rows.occurrence_year
                    IS DISTINCT FROM canonical_rows.occurrence_year
                OR fact_rows.month_id IS DISTINCT FROM CASE
                    WHEN canonical_rows.occurrence_month IS NULL THEN NULL
                    ELSE canonical_rows.occurrence_year * 100
                         + canonical_rows.occurrence_month
                END
                OR fact_rows.severity_code
                    IS DISTINCT FROM canonical_rows.severity_code
                OR fact_rows.is_fatal_crash
                    IS DISTINCT FROM canonical_rows.is_fatal_crash
                OR fact_rows.fatality_count
                    IS DISTINCT FROM canonical_rows.fatality_count
                OR fact_rows.casualty_count
                    IS DISTINCT FROM canonical_rows.casualty_count
                OR fact_rows.fatal_crash_eligible
                    IS DISTINCT FROM canonical_rows.fatal_crash_eligible
                OR fact_rows.fatality_eligible
                    IS DISTINCT FROM canonical_rows.fatality_eligible
                OR fact_rows.casualty_eligible
                    IS DISTINCT FROM canonical_rows.casualty_eligible
                OR fact_rows.latitude IS DISTINCT FROM canonical_rows.latitude
                OR fact_rows.longitude IS DISTINCT FROM canonical_rows.longitude
                OR fact_rows.map_eligible
                    IS DISTINCT FROM canonical_rows.map_eligible
            )
        ) AS field_mismatch
    FROM canonical_rows
    FULL OUTER JOIN fact_rows
      ON fact_rows.batch_id = canonical_rows.batch_id
     AND fact_rows.source_id = canonical_rows.source_id
     AND fact_rows.release_scope = canonical_rows.release_scope
     AND fact_rows.crash_key = canonical_rows.crash_key
), canonical_totals AS (
    SELECT
        count(*)::bigint AS crash_count,
        count(*) FILTER (
            WHERE fatal_crash_eligible AND is_fatal_crash IS TRUE
        )::bigint AS fatal_crash_count,
        COALESCE(sum(fatality_count) FILTER (
            WHERE fatality_eligible AND fatality_count IS NOT NULL
        ), 0)::bigint AS fatality_count,
        COALESCE(sum(casualty_count) FILTER (
            WHERE casualty_eligible AND casualty_count IS NOT NULL
        ), 0)::bigint AS casualty_count,
        count(*) FILTER (
            WHERE fatal_crash_eligible AND is_fatal_crash IS NOT NULL
        )::bigint AS fatal_crash_known_count,
        count(*) FILTER (
            WHERE fatality_eligible AND fatality_count IS NOT NULL
        )::bigint AS fatality_known_count,
        count(*) FILTER (
            WHERE casualty_eligible AND casualty_count IS NOT NULL
        )::bigint AS casualty_known_count
    FROM canonical_rows
), fact_totals AS (
    SELECT
        count(*)::bigint AS crash_count,
        count(*) FILTER (
            WHERE fatal_crash_eligible AND is_fatal_crash IS TRUE
        )::bigint AS fatal_crash_count,
        COALESCE(sum(fatality_count) FILTER (
            WHERE fatality_eligible AND fatality_count IS NOT NULL
        ), 0)::bigint AS fatality_count,
        COALESCE(sum(casualty_count) FILTER (
            WHERE casualty_eligible AND casualty_count IS NOT NULL
        ), 0)::bigint AS casualty_count,
        count(*) FILTER (
            WHERE fatal_crash_eligible AND is_fatal_crash IS NOT NULL
        )::bigint AS fatal_crash_known_count,
        count(*) FILTER (
            WHERE fatality_eligible AND fatality_count IS NOT NULL
        )::bigint AS fatality_known_count,
        count(*) FILTER (
            WHERE casualty_eligible AND casualty_count IS NOT NULL
        )::bigint AS casualty_known_count
    FROM fact_rows
)
"""


METRICS_SQL = _CTES + """
 , pair_totals AS (
    SELECT
        count(*)::bigint AS evaluated_count,
        count(*) FILTER (WHERE has_canonical AND NOT has_fact)::bigint
            AS missing_fact_count,
        count(*) FILTER (WHERE has_fact AND NOT has_canonical)::bigint
            AS extra_fact_count,
        count(*) FILTER (WHERE field_mismatch)::bigint
            AS field_mismatch_count,
        count(*) FILTER (WHERE has_canonical AND lineage_error)::bigint
            AS lineage_error_count,
        count(*) FILTER (WHERE has_canonical AND definition_error)::bigint
            AS definition_error_count,
        count(*) FILTER (
            WHERE NOT has_canonical OR NOT has_fact OR field_mismatch
               OR (has_canonical AND (lineage_error OR definition_error))
        )::bigint AS affected_count
    FROM paired
)
SELECT
    pair_totals.evaluated_count,
    canonical_totals.crash_count,
    pair_totals.missing_fact_count,
    pair_totals.extra_fact_count,
    pair_totals.field_mismatch_count,
    pair_totals.lineage_error_count,
    pair_totals.definition_error_count,
    fact_totals.crash_count - canonical_totals.crash_count,
    fact_totals.fatal_crash_count - canonical_totals.fatal_crash_count,
    fact_totals.fatality_count - canonical_totals.fatality_count,
    fact_totals.casualty_count - canonical_totals.casualty_count,
    fact_totals.fatal_crash_known_count
        - canonical_totals.fatal_crash_known_count,
    fact_totals.fatality_known_count - canonical_totals.fatality_known_count,
    fact_totals.casualty_known_count - canonical_totals.casualty_known_count,
    pair_totals.affected_count
FROM canonical_totals
CROSS JOIN fact_totals
CROSS JOIN pair_totals
"""


DETAIL_SQL = _CTES + """
SELECT
    release_scope,
    crash_key,
    NOT has_fact,
    NOT has_canonical,
    field_mismatch,
    COALESCE(lineage_error, false),
    COALESCE(definition_error, false),
    to_jsonb(canonical_row),
    to_jsonb(fact_row),
    primary_resource_id,
    primary_file_sha256,
    primary_parser_version,
    primary_row_locator,
    location_resource_id,
    location_file_sha256,
    location_parser_version,
    location_row_locator
FROM paired
WHERE NOT has_canonical OR NOT has_fact OR field_mismatch
   OR (has_canonical AND (lineage_error OR definition_error))
ORDER BY release_scope, crash_key
"""


@dataclass(frozen=True)
class _SourceYear:
    source_id: str
    year: int
    lineage_json: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_value(value: Any) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _manifest_scope(manifest: Any) -> tuple[_SourceYear, ...]:
    if not isinstance(manifest, Mapping):
        raise IntakeError("D04_MANIFEST", "D04 requires a manifest object")
    sources = manifest.get("sources")
    analysis = manifest.get("analysis")
    files = manifest.get("files")
    if (not isinstance(sources, list) or not sources
            or not isinstance(analysis, Mapping) or not isinstance(files, list)):
        raise IntakeError("D04_MANIFEST", "D04 requires sources, files and analysis")
    first, last = analysis.get("year_from"), analysis.get("year_to")
    if type(first) is not int or type(last) is not int or first > last:
        raise IntakeError("D04_MANIFEST", "D04 analysis years are invalid")
    ids: list[str] = []
    for source in sources:
        source_id = source.get("source_id") if isinstance(source, Mapping) else None
        if not isinstance(source_id, str) or not source_id.strip() or source_id in ids:
            raise IntakeError("D04_MANIFEST", "D04 source IDs are invalid")
        ids.append(source_id)
    lineage: dict[str, str] = {}
    for source_id in ids:
        allowed = []
        primary_count = 0
        for file in files:
            if not isinstance(file, Mapping) or file.get("source_id") != source_id:
                continue
            kind = file.get("entity_kind")
            if kind not in {"crash", "node_raw"}:
                continue
            required = ("resource_id", "file_sha256", "parser_version")
            if any(not isinstance(file.get(name), str) or not file[name]
                   for name in required):
                raise IntakeError("D04_MANIFEST", "D04 file identities are invalid")
            if kind == "crash":
                primary_count += 1
                allowed.append({
                    "lineage_kind": "primary",
                    **{name: file[name] for name in required},
                })
            allowed.append({
                "lineage_kind": "location",
                **{name: file[name] for name in required},
            })
        if primary_count == 0:
            raise IntakeError(
                "D04_MANIFEST",
                "Every D04 source requires a frozen crash resource",
                source_id=source_id,
            )
        lineage[source_id] = json.dumps(
            allowed, ensure_ascii=False, allow_nan=False, sort_keys=True
        )
    return tuple(
        _SourceYear(source_id, year, lineage[source_id])
        for source_id in ids for year in range(first, last + 1)
    )


def _parameters(batch_id: str, item: _SourceYear) -> tuple[Any, ...]:
    return (
        item.lineage_json,
        batch_id, item.source_id, item.year,
        batch_id, item.source_id, item.year,
    )


def _metric_row(connection: Any, batch_id: str, item: _SourceYear) -> tuple:
    with connection.cursor() as cursor:
        cursor.execute(METRICS_SQL, _parameters(batch_id, item))
        row = cursor.fetchone()
    if row is None or len(row) != 15:
        raise IntakeError(
            "D04_QUERY_SHAPE",
            "QA06 metrics query returned an unexpected result shape",
            source_id=item.source_id,
            year=item.year,
        )
    return tuple(int(value) for value in row)


def _detail_record(row: tuple, source_id: str, year: int) -> dict[str, Any]:
    if len(row) != 17:
        raise IntakeError("D04_DETAIL_SHAPE", "QA06 detail row has an unexpected shape")
    issues = [
        name for name, flagged in zip(
            (
                "MISSING_FACT", "EXTRA_FACT", "FIELD_MISMATCH",
                "LINEAGE_ERROR", "DEFINITION_ERROR",
            ),
            row[2:7],
        ) if flagged
    ]
    references = []
    for kind, values in (
        ("primary", row[9:13]),
        ("location", row[13:17]),
    ):
        resource_id, digest, parser, locator = values
        if resource_id is not None:
            references.append({
                "kind": kind,
                "resource_id": resource_id,
                "file_sha256": digest,
                "parser_version": parser,
                "row_locator": locator,
            })
    canonical = _json_value(row[7])
    fact = _json_value(row[8])
    return {
        "source_id": source_id,
        "occurrence_year": year,
        "release_scope": row[0],
        "crash_key": row[1],
        "issues": issues,
        "expected": canonical,
        "actual": fact,
        "raw_record_id": canonical.get("raw_record_id") if isinstance(canonical, dict) else None,
        "references": references,
    }


def _write_details(
    connection: Any,
    batch_id: str,
    item: _SourceYear,
    evidence: Any,
    expected_count: int,
) -> tuple[dict[str, Any], str | None]:
    directory = Path(evidence.directory)
    directory.mkdir(parents=True, exist_ok=True)
    safe_source = "".join(c if c.isalnum() or c in "_-" else "_" for c in item.source_id)
    final = directory / f"qa06-{safe_source}-{item.year}-differences.jsonl"
    digest = hashlib.sha256()
    count = 0
    first_raw: str | None = None
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            with connection.cursor() as cursor:
                cursor.execute(DETAIL_SQL, _parameters(batch_id, item))
                while True:
                    rows = cursor.fetchmany(1000)
                    if not rows:
                        break
                    for row in rows:
                        record = _detail_record(tuple(row), item.source_id, item.year)
                        first_raw = first_raw or record["raw_record_id"]
                        encoded = (
                            json.dumps(record, ensure_ascii=False, allow_nan=False,
                                       sort_keys=True) + "\n"
                        ).encode("utf-8")
                        stream.write(encoded)
                        digest.update(encoded)
                        count += 1
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, final)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    if count != expected_count:
        final.unlink(missing_ok=True)
        raise IntakeError(
            "D04_DETAIL_COUNT",
            "QA06 detail evidence does not cover every affected identity",
            source_id=item.source_id,
            year=item.year,
            expected_count=expected_count,
            actual_count=count,
        )
    return {
        "path": str(final),
        "sha256": digest.hexdigest(),
        "row_count": count,
        "source_id": item.source_id,
        "occurrence_year": item.year,
    }, first_raw


def _reason_codes(metrics: Mapping[str, int]) -> list[str]:
    names = {
        "missing_fact_count": "MISSING_FACT",
        "extra_fact_count": "EXTRA_FACT",
        "field_mismatch_count": "FIELD_MISMATCH",
        "lineage_error_count": "LINEAGE_ERROR",
        "definition_error_count": "DEFINITION_ERROR",
        "crash_delta": "CRASH_DELTA",
        "fatal_crash_delta": "FATAL_CRASH_DELTA",
        "fatality_delta": "FATALITY_DELTA",
        "casualty_delta": "CASUALTY_DELTA",
        "fatal_crash_known_delta": "FATAL_CRASH_KNOWN_DELTA",
        "fatality_known_delta": "FATALITY_KNOWN_DELTA",
        "casualty_known_delta": "CASUALTY_KNOWN_DELTA",
    }
    return [names[name] for name in METRIC_NAMES if metrics[name] != 0]


def reconcile(
    connection: Any,
    batch_id: Any,
    manifest: Mapping[str, Any],
    *,
    evidence: Any | None = None,
    producer_version: str = PRODUCER_VERSION,
) -> QAReport:
    """Return complete QA06 source-year rows and a batch summary."""

    try:
        batch = str(UUID(str(batch_id)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise IntakeError("D04_BATCH_ID", "D04 batch_id must be a UUID") from exc
    if not isinstance(producer_version, str) or not producer_version.strip():
        raise IntakeError("D04_VERSION", "D04 requires a producer version")

    rows: list[dict[str, Any]] = []
    zeros = dict.fromkeys(METRIC_NAMES, 0)
    for item in _manifest_scope(manifest):
        values = _metric_row(connection, batch, item)
        evaluated, expected_count, *metric_values, affected = values
        metrics = dict(zip(METRIC_NAMES, metric_values, strict=True))
        reasons = _reason_codes(metrics)
        references: list[dict[str, Any]] = [{
            "source_id": item.source_id,
            "occurrence_year": item.year,
            "batch_id": batch,
        }]
        raw_record_id = None
        if affected:
            if evidence is None:
                references.append({
                    "detail": "Difference evidence unavailable: no RunEvidence supplied",
                    "row_count": affected,
                })
            else:
                detail, raw_record_id = _write_details(
                    connection, batch, item, evidence, affected
                )
                references.append(detail)
        result = "block" if reasons or affected else "pass"
        rows.append({
            "rule_id": RULE_ID,
            "object_key": f"source_year:{item.source_id}:{item.year}",
            "result": result,
            "affected_count": affected,
            "actual": {
                "evaluated_count": evaluated,
                "violation_count": affected,
                "metrics": metrics,
            },
            "expected": {
                "evaluated_count": expected_count,
                "violation_count": 0,
                "metrics": dict(zeros),
            },
            "evidence": {
                "reason_codes": reasons,
                "resolution": (
                    "Resolve the located Canonical/fact differences before publication."
                    if result == "block"
                    else "Canonical and fact rows, lineage, definitions and aggregates agree."
                ),
                "references": references,
                "producer_version": producer_version,
            },
            "raw_record_id": raw_record_id,
            "checked_at": _now(),
        })

    blocks = sum(row["result"] == "block" for row in rows)
    count = len(rows)
    summary_metrics = {
        "object_count": count,
        "pass_count": count - blocks,
        "limited_count": 0,
        "block_count": blocks,
        "missing_count": 0,
    }
    rows.append({
        "rule_id": RULE_ID,
        "object_key": "batch",
        "result": "block" if blocks else "pass",
        "affected_count": sum(row["affected_count"] for row in rows),
        "actual": {
            "evaluated_count": count,
            "violation_count": blocks,
            "metrics": summary_metrics,
        },
        "expected": {
            "evaluated_count": count,
            "violation_count": 0,
            "metrics": {
                "object_count": count,
                "pass_count": count,
                "limited_count": 0,
                "block_count": 0,
                "missing_count": 0,
            },
        },
        "evidence": {
            "reason_codes": ["SOURCE_YEAR_RECONCILIATION_BLOCKED"] if blocks else [],
            "resolution": "See each source-year QA06 result.",
            "references": [
                {"object_key": row["object_key"], "result": row["result"]}
                for row in rows
            ],
            "producer_version": producer_version,
        },
        "raw_record_id": None,
        "checked_at": _now(),
    })
    return QAReport(tuple(rows))


def runner_callback(connection: Any, context: Any) -> dict[str, int]:
    """B10 qa_d callback; write QA06 without owning the transaction."""

    report = reconcile(
        connection,
        context.batch_id,
        context.manifest.as_dict(),
        evidence=getattr(context, "evidence", None),
    )
    write_results(connection, context.batch_id, report)
    concrete = report.rows[:-1]
    counts = {
        "qa06_object_count": len(concrete),
        "qa06_pass_count": sum(row["result"] == "pass" for row in concrete),
        "qa06_block_count": sum(row["result"] == "block" for row in concrete),
    }
    evidence = getattr(context, "evidence", None)
    if evidence is not None:
        evidence.write_json(
            "d04-qa06-summary.json",
            {"batch_id": str(context.batch_id), **counts},
        )
    return counts
