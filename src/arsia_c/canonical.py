from __future__ import annotations

from collections import defaultdict
import json

from arsia_ingest.models import IntakeError
from arsia_ingest.vault_load import iter_satellites
from arsia_c.canonical_validation import validate_values, validate_snapshot, reconcile

CRASH_ATTRIBUTE_KEYS = {
    "occurrence_year",
    "occurrence_month",
    "occurrence_date",
    "date_precision",
    "severity_raw",
    "severity_code",
    "severity_definition_version",
    "is_fatal_crash",
    "fatality_count",
    "casualty_count",
    "fatal_crash_eligible",
    "fatality_eligible",
    "casualty_eligible",
    "latitude",
    "longitude",
    "location_crs",
    "map_eligible",
    "location_record_id",
    "quality_notes",
}

UNIT_ATTRIBUTE_KEYS = {
    "crash_key",
    "unit_type_raw",
    "unit_type_code",
    "statistical_scope",
    "count_eligible",
    "quality_notes",
}

CRASH_INSERT_SQL = """
INSERT INTO canonical.crash (
    batch_id,
    source_id,
    release_scope,
    crash_key,
    raw_record_id,
    occurrence_year,
    occurrence_month,
    occurrence_date,
    date_precision,
    severity_raw,
    severity_code,
    severity_definition_version,
    is_fatal_crash,
    fatality_count,
    casualty_count,
    fatal_crash_eligible,
    fatality_eligible,
    casualty_eligible,
    latitude,
    longitude,
    location_crs,
    map_eligible,
    location_record_id,
    quality_notes
)
VALUES (
    %s::uuid,
    %s::text,
    %s::text,
    %s::text,
    %s::uuid,
    %s::integer,
    %s::integer,
    %s::date,
    %s::text,
    %s::text,
    %s::text,
    %s::text,
    %s::boolean,
    %s::integer,
    %s::integer,
    %s::boolean,
    %s::boolean,
    %s::boolean,
    %s::numeric(10,7),
    %s::numeric(10,7),
    %s::text,
    %s::boolean,
    %s::uuid,
    %s::jsonb
)
"""

UNIT_INSERT_SQL = """
INSERT INTO canonical.unit (
    batch_id,
    source_id,
    release_scope,
    unit_key,
    crash_key,
    raw_record_id,
    unit_type_raw,
    unit_type_code,
    statistical_scope,
    count_eligible,
    quality_notes
)
VALUES (
    %s::uuid,
    %s::text,
    %s::text,
    %s::text,
    %s::text,
    %s::uuid,
    %s::text,
    %s::text,
    %s::text,
    %s::boolean,
    %s::jsonb
)
"""


def _allowed_scopes(manifest: dict) -> set[tuple[str, str]]:
    return {
        (source["source_id"], source["release_scope"]) for source in manifest["sources"]
    }


def _validate_satellite_identity(
    row: dict,
    *,
    batch_id,
    allowed_scopes: set[tuple[str, str]],
    entity_kind: str,
) -> None:
    if str(row["batch_id"]) != str(batch_id):
        raise IntakeError(
            "CANONICAL_BATCH",
            "Satellite row belongs to a different batch",
            entity_kind=entity_kind,
            actual_batch_id=str(row["batch_id"]),
            expected_batch_id=str(batch_id),
        )

    scope = (row["source_id"], row["release_scope"])

    if scope not in allowed_scopes:
        raise IntakeError(
            "CANONICAL_SCOPE",
            "Satellite row belongs to a source/release outside the frozen manifest",
            entity_kind=entity_kind,
            source_id=row["source_id"],
            release_scope=row["release_scope"],
        )


def _validate_attributes(
    attributes,
    *,
    expected: set[str],
    entity_kind: str,
    key: str,
) -> None:
    if not isinstance(attributes, dict):
        raise IntakeError(
            "CANONICAL_ATTRIBUTES",
            "Satellite attributes must be a JSON object",
            entity_kind=entity_kind,
            key=key,
        )

    actual = set(attributes)

    if actual != expected:
        raise IntakeError(
            "CANONICAL_ATTRIBUTES",
            "Satellite attributes do not match the fixed Canonical attribute contract",
            entity_kind=entity_kind,
            key=key,
            missing=sorted(expected - actual),
            unexpected=sorted(actual - expected),
        )


def _crash_parameters(
    row: dict,
    *,
    batch_id,
    allowed_scopes: set[tuple[str, str]],
) -> tuple:
    _validate_satellite_identity(
        row,
        batch_id=batch_id,
        allowed_scopes=allowed_scopes,
        entity_kind="crash",
    )

    attributes = row["attributes"]

    _validate_attributes(
        attributes,
        expected=CRASH_ATTRIBUTE_KEYS,
        entity_kind="crash",
        key=row["crash_key"],
    )

    validate_values(attributes, "crash")

    return (
        row["batch_id"],
        row["source_id"],
        row["release_scope"],
        row["crash_key"],
        row["raw_record_id"],
        attributes["occurrence_year"],
        attributes["occurrence_month"],
        attributes["occurrence_date"],
        attributes["date_precision"],
        attributes["severity_raw"],
        attributes["severity_code"],
        attributes["severity_definition_version"],
        attributes["is_fatal_crash"],
        attributes["fatality_count"],
        attributes["casualty_count"],
        attributes["fatal_crash_eligible"],
        attributes["fatality_eligible"],
        attributes["casualty_eligible"],
        attributes["latitude"],
        attributes["longitude"],
        attributes["location_crs"],
        attributes["map_eligible"],
        attributes["location_record_id"],
        json.dumps(attributes["quality_notes"]),
    )


def _unit_parameters(
    row: dict,
    *,
    batch_id,
    allowed_scopes: set[tuple[str, str]],
) -> tuple:
    _validate_satellite_identity(
        row,
        batch_id=batch_id,
        allowed_scopes=allowed_scopes,
        entity_kind="unit",
    )

    attributes = row["attributes"]

    _validate_attributes(
        attributes,
        expected=UNIT_ATTRIBUTE_KEYS,
        entity_kind="unit",
        key=row["unit_key"],
    )

    if attributes["crash_key"] != row["crash_key"]:
        raise IntakeError(
            "CANONICAL_PARENT",
            "Unit Satellite parent does not match the Vault crash-unit Link",
            unit_key=row["unit_key"],
            satellite_crash_key=attributes["crash_key"],
            link_crash_key=row["crash_key"],
        )

    validate_values(attributes, "unit")

    return (
        row["batch_id"],
        row["source_id"],
        row["release_scope"],
        row["unit_key"],
        row["crash_key"],
        row["raw_record_id"],
        attributes["unit_type_raw"],
        attributes["unit_type_code"],
        attributes["statistical_scope"],
        attributes["count_eligible"],
        json.dumps(attributes["quality_notes"]),
    )


def load_canonical(connection, context) -> None:
    """B10 Canonical callback; rebuild only from selected current-batch Satellites."""
    validate_snapshot(connection, context)
    manifest = context.manifest.as_dict()
    allowed_scopes = _allowed_scopes(manifest)

    source_counts = defaultdict(lambda: {"crash_count": 0, "unit_count": 0})

    crash_rows = (
        _crash_parameters(
            row,
            batch_id=context.batch_id,
            allowed_scopes=allowed_scopes,
        )
        for row in iter_satellites(connection, context, "crash")
    )

    with connection.cursor() as cursor:
        crash_count = 0
        pending = []

        for parameters in crash_rows:
            pending.append(parameters)
            source_counts[parameters[1]]["crash_count"] += 1

            if len(pending) >= 1000:
                cursor.executemany(CRASH_INSERT_SQL, pending)
                crash_count += len(pending)
                pending.clear()

        if pending:
            cursor.executemany(CRASH_INSERT_SQL, pending)
            crash_count += len(pending)

    unit_rows = (
        _unit_parameters(
            row,
            batch_id=context.batch_id,
            allowed_scopes=allowed_scopes,
        )
        for row in iter_satellites(connection, context, "unit")
    )

    with connection.cursor() as cursor:
        unit_count = 0
        pending = []

        for parameters in unit_rows:
            pending.append(parameters)
            source_counts[parameters[1]]["unit_count"] += 1

            if len(pending) >= 1000:
                cursor.executemany(UNIT_INSERT_SQL, pending)
                unit_count += len(pending)
                pending.clear()

        if pending:
            cursor.executemany(UNIT_INSERT_SQL, pending)
            unit_count += len(pending)

    counts = reconcile(connection, context)
    if counts != {"crash": crash_count, "unit": unit_count}:
        raise IntakeError(
            "CANONICAL_COUNTS", "Inserted counts differ from the database"
        )

    context.evidence.write_json(
        "c09-canonical-counts.json",
        {
            "batch_id": str(context.batch_id),
            "crash_count": crash_count,
            "unit_count": unit_count,
            "sources": dict(source_counts),
            "source": "selected_raw_vault_satellites",
            "raw_recomputed": False,
            "satellite_reconciled": True,
            "lineage_validated": True,
        },
    )
