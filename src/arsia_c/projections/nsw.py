from __future__ import annotations

from pathlib import Path


NSW_CRASH_RESOURCE_ID = "official_nsw_crash"
NSW_TRAFFIC_UNIT_RESOURCE_ID = "official_nsw_traffic_unit"

PROJECTION_TABLES_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_projection_tables.sql"
)

RELATIONSHIP_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_relationship_check.sql"
)

MONTH_CHECK_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_month_check.sql"
)


def _contract_by_id(manifest: dict, resource_id: str) -> dict:
    contracts = manifest["rules"]["contracts"]

    matches = [
        contract
        for contract in contracts
        if contract["id"] == resource_id
    ]

    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one contract for {resource_id}, "
            f"found {len(matches)}"
        )

    return matches[0]


def _load_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _validate_relationship_counts(counts) -> None:
    if counts is None:
        raise ValueError("NSW relationship check returned no result")

    (
        crash_blank_key_count,
        crash_duplicate_key_count,
        unit_blank_key_count,
        unit_duplicate_key_count,
        orphan_unit_count,
    ) = counts

    failures = {
        "crash_blank_key_count": crash_blank_key_count,
        "crash_duplicate_key_count": crash_duplicate_key_count,
        "unit_blank_key_count": unit_blank_key_count,
        "unit_duplicate_key_count": unit_duplicate_key_count,
        "orphan_unit_count": orphan_unit_count,
    }

    nonzero = {
        name: value
        for name, value in failures.items()
        if value != 0
    }

    if nonzero:
        raise ValueError(
            f"NSW relationship validation failed: {nonzero}"
        )


def project(connection, context) -> None:
    manifest = context.manifest.as_dict()

    crash_contract = _contract_by_id(
        manifest,
        NSW_CRASH_RESOURCE_ID,
    )

    unit_contract = _contract_by_id(
        manifest,
        NSW_TRAFFIC_UNIT_RESOURCE_ID,
    )

    crash_input = crash_contract["content"]["input"]
    unit_input = unit_contract["content"]["input"]

    batch_id = context.batch_id

    cursor = connection.cursor()

    # Create C-to-A temporary projection tables.
    projection_tables_sql = _load_sql(PROJECTION_TABLES_SQL_PATH)
    cursor.execute(projection_tables_sql)

    # Validate Crash / Traffic Unit keys and parent relationships
    # against the complete frozen snapshot before year filtering.
    relationship_sql = _load_sql(RELATIONSHIP_SQL_PATH)

    cursor.execute(
        relationship_sql,
        (
            crash_input["source_id"],
            crash_input["resource_id"],
            crash_input["file_sha256"],
            crash_input["parser_version"],
            unit_input["source_id"],
            unit_input["resource_id"],
            unit_input["file_sha256"],
            unit_input["parser_version"],
        ),
    )

    relationship_counts = cursor.fetchone()
    _validate_relationship_counts(relationship_counts)

    # Validate NSW native month values.
    month_check_sql = _load_sql(MONTH_CHECK_SQL_PATH)

    cursor.execute(
        month_check_sql,
        (
            crash_input["source_id"],
            crash_input["resource_id"],
            crash_input["file_sha256"],
            crash_input["parser_version"],
        ),
    )

    month_check_result = cursor.fetchone()

    if month_check_result is None:
        raise ValueError("NSW month validation returned no result")

    unknown_month_count = month_check_result[0]

    if unknown_month_count != 0:
        raise ValueError(
            f"NSW month validation failed: "
            f"unknown_month_count={unknown_month_count}"
        )

    # Crash and Unit projection inserts are added next.
    _ = batch_id
