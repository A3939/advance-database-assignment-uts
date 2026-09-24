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

YEAR_CHECK_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_year_check.sql"
)

MONTH_CHECK_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_month_check.sql"
)

SEMANTIC_CHECK_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_semantic_check.sql"
)

CRASH_INSERT_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_crash_insert.sql"
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
        raise ValueError(
            "NSW relationship check returned no result"
        )

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


def _validate_year(cursor, crash_input: dict) -> None:
    year_check_sql = _load_sql(
        YEAR_CHECK_SQL_PATH
    )

    cursor.execute(
        year_check_sql,
        (
            crash_input["source_id"],
            crash_input["resource_id"],
            crash_input["file_sha256"],
            crash_input["parser_version"],
        ),
    )

    result = cursor.fetchone()

    if result is None:
        raise ValueError(
            "NSW year validation returned no result"
        )

    invalid_year_count = result[0]

    if invalid_year_count != 0:
        raise ValueError(
            "NSW year validation failed: "
            f"invalid_year_count={invalid_year_count}"
        )


def _validate_month(cursor, crash_input: dict) -> None:
    month_check_sql = _load_sql(
        MONTH_CHECK_SQL_PATH
    )

    cursor.execute(
        month_check_sql,
        (
            crash_input["source_id"],
            crash_input["resource_id"],
            crash_input["file_sha256"],
            crash_input["parser_version"],
        ),
    )

    result = cursor.fetchone()

    if result is None:
        raise ValueError(
            "NSW month validation returned no result"
        )

    unknown_month_count = result[0]

    if unknown_month_count != 0:
        raise ValueError(
            "NSW month validation failed: "
            f"unknown_month_count={unknown_month_count}"
        )


def _validate_semantics(cursor, crash_input: dict) -> None:
    semantic_check_sql = _load_sql(
        SEMANTIC_CHECK_SQL_PATH
    )

    cursor.execute(
        semantic_check_sql,
        (
            crash_input["source_id"],
            crash_input["resource_id"],
            crash_input["file_sha256"],
            crash_input["parser_version"],
        ),
    )

    result = cursor.fetchone()

    if result is None:
        raise ValueError(
            "NSW semantic validation returned no result"
        )

    (
        unknown_severity_count,
        invalid_fatality_count,
        invalid_serious_count,
        invalid_moderate_count,
        invalid_minor_other_count,
    ) = result

    failures = {
        "unknown_severity_count":
            unknown_severity_count,
        "invalid_fatality_count":
            invalid_fatality_count,
        "invalid_serious_count":
            invalid_serious_count,
        "invalid_moderate_count":
            invalid_moderate_count,
        "invalid_minor_other_count":
            invalid_minor_other_count,
    }

    nonzero = {
        name: value
        for name, value in failures.items()
        if value != 0
    }

    if nonzero:
        raise ValueError(
            f"NSW semantic validation failed: {nonzero}"
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

    crash_input = (
        crash_contract["content"]["input"]
    )

    unit_input = (
        unit_contract["content"]["input"]
    )

    batch_id = context.batch_id

    cursor = connection.cursor()

    # 1. Create the C-to-A temporary projection tables.
    projection_tables_sql = _load_sql(
        PROJECTION_TABLES_SQL_PATH
    )

    cursor.execute(
        projection_tables_sql
    )

    # 2. Validate Crash / Traffic Unit keys and
    # parent relationships against the complete
    # frozen snapshot before year filtering.
    relationship_sql = _load_sql(
        RELATIONSHIP_SQL_PATH
    )

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

    _validate_relationship_counts(
        relationship_counts
    )

    # 3. Validate occurrence year before
    # downstream integer casts.
    _validate_year(
        cursor,
        crash_input,
    )

    # 4. Validate NSW month vocabulary.
    _validate_month(
        cursor,
        crash_input,
    )

    # 5. Validate severity and count semantics.
    _validate_semantics(
        cursor,
        crash_input,
    )

    # 6. Read confirmed rule values from
    # the frozen NSW source contract.
    release_scope = (
        crash_contract["content"]["identity"][
            "release_scope"
        ]
    )

    severity_definition_version = (
        crash_contract["content"]["semantics"][
            "severity_definition_version"
        ]
    )

    # 7. Insert NSW Crash projection rows.
    crash_insert_sql = _load_sql(
        CRASH_INSERT_SQL_PATH
    )

    cursor.execute(
        crash_insert_sql,
        (
            batch_id,
            release_scope,
            severity_definition_version,
            crash_input["source_id"],
            crash_input["resource_id"],
            crash_input["file_sha256"],
            crash_input["parser_version"],
        ),
    )

    crash_projection_count = cursor.rowcount

    if crash_projection_count < 0:
        raise ValueError(
            "NSW Crash projection did not return "
            "a valid inserted-row count"
        )

    # 8. NSW Traffic Unit projection is added next.
    _ = crash_projection_count
