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

UNIT_CHECK_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_unit_check.sql"
)

CRASH_INSERT_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_crash_insert.sql"
)

UNIT_INSERT_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_unit_insert.sql"
)

PROJECTION_CHECK_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_projection_check.sql"
)


def _contract_by_id(
    manifest: dict,
    resource_id: str,
) -> dict:
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


def _mapping_by_id(
    manifest: dict,
    mapping_id: str,
) -> dict:
    mappings = manifest["rules"]["mappings"]

    matches = [
        mapping
        for mapping in mappings
        if mapping["id"] == mapping_id
    ]

    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one mapping for {mapping_id}, "
            f"found {len(matches)}"
        )

    return matches[0]


def _load_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _validate_relationship_counts(
    counts,
) -> None:
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
        "crash_blank_key_count":
            crash_blank_key_count,
        "crash_duplicate_key_count":
            crash_duplicate_key_count,
        "unit_blank_key_count":
            unit_blank_key_count,
        "unit_duplicate_key_count":
            unit_duplicate_key_count,
        "orphan_unit_count":
            orphan_unit_count,
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


def _validate_year(
    cursor,
    crash_input: dict,
) -> None:
    sql = _load_sql(YEAR_CHECK_SQL_PATH)

    cursor.execute(
        sql,
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


def _validate_month(
    cursor,
    crash_input: dict,
) -> None:
    sql = _load_sql(MONTH_CHECK_SQL_PATH)

    cursor.execute(
        sql,
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


def _validate_semantics(
    cursor,
    crash_input: dict,
) -> None:
    sql = _load_sql(SEMANTIC_CHECK_SQL_PATH)

    cursor.execute(
        sql,
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


def _validate_unit_types(
    cursor,
    crash_input: dict,
    unit_input: dict,
) -> int:
    sql = _load_sql(UNIT_CHECK_SQL_PATH)

    cursor.execute(
        sql,
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

    result = cursor.fetchone()

    if result is None:
        raise ValueError(
            "NSW Traffic Unit validation returned no result"
        )

    (
        missing_unit_type_count,
        unknown_unit_type_count,
    ) = result

    if unknown_unit_type_count != 0:
        raise ValueError(
            "NSW Traffic Unit validation failed: "
            f"unknown_unit_type_count="
            f"{unknown_unit_type_count}"
        )

    return missing_unit_type_count


def _check_projection(
    cursor,
    *,
    batch_id,
    source_id: str,
    release_scope: str,
    inserted_crash_count: int,
    inserted_unit_count: int,
) -> dict:
    sql = _load_sql(PROJECTION_CHECK_SQL_PATH)

    cursor.execute(
        sql,
        (
            batch_id,
            source_id,
            release_scope,
            batch_id,
            source_id,
            release_scope,
        ),
    )

    result = cursor.fetchone()

    if result is None:
        raise ValueError(
            "NSW projection reconciliation returned no result"
        )

    (
        crash_projection_count,
        unit_projection_count,
        duplicate_crash_key_count,
        duplicate_unit_key_count,
        orphan_projected_unit_count,
        fatal_crash_count,
        fatality_count,
        casualty_count,
        map_eligible_count,
    ) = result

    blockers = {
        "duplicate_crash_key_count":
            duplicate_crash_key_count,
        "duplicate_unit_key_count":
            duplicate_unit_key_count,
        "orphan_projected_unit_count":
            orphan_projected_unit_count,
        "map_eligible_count":
            map_eligible_count,
    }

    nonzero_blockers = {
        name: value
        for name, value in blockers.items()
        if value != 0
    }

    if nonzero_blockers:
        raise ValueError(
            "NSW projection reconciliation failed: "
            f"{nonzero_blockers}"
        )

    if crash_projection_count != inserted_crash_count:
        raise ValueError(
            "NSW Crash projection count mismatch: "
            f"inserted={inserted_crash_count}, "
            f"selected={crash_projection_count}"
        )

    if unit_projection_count != inserted_unit_count:
        raise ValueError(
            "NSW Traffic Unit projection count mismatch: "
            f"inserted={inserted_unit_count}, "
            f"selected={unit_projection_count}"
        )

    return {
        "crash_projection_count":
            crash_projection_count,
        "unit_projection_count":
            unit_projection_count,
        "duplicate_crash_key_count":
            duplicate_crash_key_count,
        "duplicate_unit_key_count":
            duplicate_unit_key_count,
        "orphan_projected_unit_count":
            orphan_projected_unit_count,
        "fatal_crash_count":
            fatal_crash_count,
        "fatality_count":
            fatality_count,
        "casualty_count":
            casualty_count,
        "map_eligible_count":
            map_eligible_count,
    }


def project(
    connection,
    context,
) -> None:
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

    unit_mapping_ids = unit_contract["mapping_ids"]

    if len(unit_mapping_ids) != 1:
        raise ValueError(
            "NSW Traffic Unit contract must reference "
            "exactly one projection mapping"
        )

    unit_mapping = _mapping_by_id(
        manifest,
        unit_mapping_ids[0],
    )

    batch_id = context.batch_id

    cursor = connection.cursor()

    # 1. Create temporary C-to-A projection tables.
    cursor.execute(
        _load_sql(PROJECTION_TABLES_SQL_PATH)
    )

    # 2. Validate complete native Crash / Unit keys
    # and relationships before year filtering.
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

    _validate_relationship_counts(
        cursor.fetchone()
    )

    # 3-6. Source-semantic validation.
    _validate_year(
        cursor,
        crash_input,
    )

    _validate_month(
        cursor,
        crash_input,
    )

    _validate_semantics(
        cursor,
        crash_input,
    )

    missing_unit_type_count = _validate_unit_types(
        cursor,
        crash_input,
        unit_input,
    )

    # 7. Read frozen NSW rule values.
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

    unit_release_scope = (
        unit_contract["content"]["identity"][
            "release_scope"
        ]
    )

    if unit_release_scope != release_scope:
        raise ValueError(
            "NSW Crash and Traffic Unit release scopes differ: "
            f"{release_scope!r} != {unit_release_scope!r}"
        )

    if unit_input["source_id"] != crash_input["source_id"]:
        raise ValueError(
            "NSW Crash and Traffic Unit source IDs differ"
        )

    statistical_scope = (
        unit_mapping["content"][
            "statistical_scope"
        ]
    )

    # 8. Insert Crash projection.
    cursor.execute(
        _load_sql(CRASH_INSERT_SQL_PATH),
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

    # 9. Insert Traffic Unit projection.
    cursor.execute(
        _load_sql(UNIT_INSERT_SQL_PATH),
        (
            batch_id,
            unit_release_scope,
            statistical_scope,
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

    unit_projection_count = cursor.rowcount

    if unit_projection_count < 0:
        raise ValueError(
            "NSW Traffic Unit projection did not return "
            "a valid inserted-row count"
        )

    # 10. Reconcile the completed projection.
    counts = _check_projection(
        cursor,
        batch_id=batch_id,
        source_id=crash_input["source_id"],
        release_scope=release_scope,
        inserted_crash_count=crash_projection_count,
        inserted_unit_count=unit_projection_count,
    )

    counts["missing_unit_type_count"] = (
        missing_unit_type_count
    )

    counts["source_id"] = (
        crash_input["source_id"]
    )

    counts["release_scope"] = (
        release_scope
    )

    # 11. Record C03 build evidence for B10.
    context.evidence.write_json(
        "c03-nsw-projection-counts.json",
        counts,
    )
    
