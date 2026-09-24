from __future__ import annotations

import json
from pathlib import Path
from typing import Any


QA03_SQL_PATH = (
    Path(__file__).resolve().parents[2]
    / "sql"
    / "qa"
    / "c10_qa03_projected.sql"
)

QA03_EXPECTATION_SQL_PATH = (
    Path(__file__).resolve().parents[2]
    / "sql"
    / "qa"
    / "c10_qa03_expectation.sql"
)

PRODUCER_VERSION = "c10-role-c-v0.2"


def _load_sql(path: Path) -> str:
    """
    Load a project SQL file as UTF-8 text.
    """

    return path.read_text(
        encoding="utf-8"
    )


def _manifest_file(
    manifest: dict,
    resource_id: str,
) -> dict:
    """
    Return exactly one frozen manifest file object
    for the requested resource.
    """

    matches = [
        item
        for item in manifest["files"]
        if item["resource_id"] == resource_id
    ]

    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one frozen file for "
            f"{resource_id!r}; found {len(matches)}"
        )

    return matches[0]


def _manifest_source(
    manifest: dict,
    source_id: str,
) -> dict:
    """
    Return exactly one frozen source object.
    """

    matches = [
        item
        for item in manifest["sources"]
        if item["source_id"] == source_id
    ]

    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one frozen source for "
            f"{source_id!r}; found {len(matches)}"
        )

    return matches[0]


def _parent_crash_file(
    manifest: dict,
    source_id: str,
) -> dict:
    """
    Find the crash resource that owns the parent
    occurrence scope for a unit resource.
    """

    matches = [
        item
        for item in manifest["files"]
        if (
            item["source_id"] == source_id
            and item["entity_kind"] == "crash"
        )
    ]

    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one frozen crash "
            f"resource for {source_id!r}; "
            f"found {len(matches)}"
        )

    return matches[0]


def _reference_for_file(
    file_info: dict,
) -> dict:
    """
    Build a compact QA evidence reference for
    one frozen Raw resource.
    """

    return {
        "resource_id":
            file_info["resource_id"],

        "file_sha256":
            file_info["file_sha256"],

        "parser_version":
            file_info["parser_version"],
    }


def derive_qa03_expectation(
    connection,
    manifest: dict,
    *,
    resource_id: str,
) -> dict:
    """
    Independently derive the QA03 expectation
    from frozen manifest identity + Raw data.

    This function MUST NOT read projection output.

    Returned counts:

    expected_input_count:
        Frozen manifest raw_count.

    actual_input_count:
        Number of Raw rows currently present for the
        exact resource/hash/parser identity.

    excluded_count:
        Number of valid Raw rows outside the configured
        occurrence-year scope, after resolving the full
        parent relationship where required.

    expected_projected_count:
        actual_input_count - excluded_count.

    The distinction between expected_input_count and
    actual_input_count allows QA03 to detect a Raw
    coverage mismatch independently from projection
    correctness.
    """

    file_info = _manifest_file(
        manifest,
        resource_id,
    )

    source_id = file_info["source_id"]
    entity_kind = file_info["entity_kind"]

    if source_id not in {
        "official_nsw",
        "official_vic",
    }:
        raise ValueError(
            "Current C10 QA03 expectation derivation "
            "supports official_nsw and official_vic only"
        )

    if entity_kind not in {
        "crash",
        "unit",
    }:
        raise ValueError(
            "QA03_PROJECTED applies only to "
            "crash/unit resources"
        )

    analysis = manifest["analysis"]

    year_from = int(
        analysis["year_from"]
    )

    year_to = int(
        analysis["year_to"]
    )

    if year_from > year_to:
        raise ValueError(
            "Manifest analysis year_from cannot "
            "exceed year_to"
        )

    parent = None

    if entity_kind == "unit":
        parent = _parent_crash_file(
            manifest,
            source_id,
        )

    params = {
        "source_id":
            source_id,

        "entity_kind":
            entity_kind,

        "resource_id":
            resource_id,

        "file_sha256":
            file_info["file_sha256"],

        "parser_version":
            file_info["parser_version"],

        "parent_resource_id":
            (
                parent["resource_id"]
                if parent is not None
                else None
            ),

        "parent_file_sha256":
            (
                parent["file_sha256"]
                if parent is not None
                else None
            ),

        "parent_parser_version":
            (
                parent["parser_version"]
                if parent is not None
                else None
            ),

        "year_from":
            year_from,

        "year_to":
            year_to,
    }

    sql = _load_sql(
        QA03_EXPECTATION_SQL_PATH
    )

    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            (
                json.dumps(params),
            ),
        )

        row = cursor.fetchone()

    if row is None:
        raise ValueError(
            "QA03 expectation query returned no row"
        )

    (
        actual_input_count,
        excluded_count,
    ) = row

    if actual_input_count is None:
        raise ValueError(
            "QA03 expectation did not return "
            "actual_input_count"
        )

    if excluded_count is None:
        raise ValueError(
            "Unsupported QA03 source/entity "
            "combination"
        )

    actual_input_count = int(
        actual_input_count
    )

    excluded_count = int(
        excluded_count
    )

    expected_input_count = int(
        file_info["raw_count"]
    )

    if actual_input_count < 0:
        raise ValueError(
            "QA03 actual_input_count cannot "
            "be negative"
        )

    if excluded_count < 0:
        raise ValueError(
            "QA03 excluded_count cannot "
            "be negative"
        )

    if excluded_count > actual_input_count:
        raise ValueError(
            "QA03 excluded_count cannot exceed "
            "actual_input_count"
        )

    references = [
        _reference_for_file(
            file_info
        )
    ]

    if parent is not None:
        references.append(
            _reference_for_file(
                parent
            )
        )

    return {
        "source_id":
            source_id,

        "resource_id":
            resource_id,

        "entity_kind":
            entity_kind,

        "expected_input_count":
            expected_input_count,

        "actual_input_count":
            actual_input_count,

        "excluded_count":
            excluded_count,

        "expected_projected_count":
            (
                actual_input_count
                - excluded_count
            ),

        "year_from":
            year_from,

        "year_to":
            year_to,

        "references":
            references,
    }


def evaluate_qa03_resource(
    connection,
    *,
    batch_id,
    release_scope: str,
    expectation: dict,
) -> dict:
    """
    Evaluate one QA03_PROJECTED object.

    The expectation must have already been derived
    independently from Raw + frozen manifest data.

    This function checks the projected temp tables:

        pg_temp.arsia_i_crash
        pg_temp.arsia_i_unit

    It does not derive the expected scope from those
    projection tables.
    """

    source_id = expectation["source_id"]
    resource_id = expectation["resource_id"]
    entity_kind = expectation["entity_kind"]

    expected_input_count = int(
        expectation["expected_input_count"]
    )

    actual_input_count = int(
        expectation["actual_input_count"]
    )

    excluded_count = int(
        expectation["excluded_count"]
    )

    expected_projected_count = int(
        expectation[
            "expected_projected_count"
        ]
    )

    references = list(
        expectation.get(
            "references",
            [],
        )
    )

    if entity_kind not in {
        "crash",
        "unit",
    }:
        raise ValueError(
            "QA03 entity_kind must be "
            "'crash' or 'unit'"
        )

    if not source_id:
        raise ValueError(
            "QA03 source_id is required"
        )

    if not resource_id:
        raise ValueError(
            "QA03 resource_id is required"
        )

    if not release_scope:
        raise ValueError(
            "QA03 release_scope is required"
        )

    if expected_input_count < 0:
        raise ValueError(
            "QA03 expected_input_count cannot "
            "be negative"
        )

    if actual_input_count < 0:
        raise ValueError(
            "QA03 actual_input_count cannot "
            "be negative"
        )

    if excluded_count < 0:
        raise ValueError(
            "QA03 excluded_count cannot "
            "be negative"
        )

    if excluded_count > actual_input_count:
        raise ValueError(
            "QA03 excluded_count cannot exceed "
            "actual_input_count"
        )

    params = {
        "entity_kind":
            entity_kind,

        "batch_id":
            str(batch_id),

        "source_id":
            source_id,

        "release_scope":
            release_scope,

        # Important:
        # SQL projection expectation is based on
        # independently counted actual Raw rows.
        "input_count":
            actual_input_count,

        "excluded_count":
            excluded_count,
    }

    sql = _load_sql(
        QA03_SQL_PATH
    )

    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            (
                json.dumps(params),
            ),
        )

        row = cursor.fetchone()

    if row is None:
        raise ValueError(
            "QA03_PROJECTED returned no result"
        )

    (
        returned_entity_kind,
        sql_input_count,
        sql_excluded_count,
        sql_expected_projected_count,
        projected_count,
        duplicate_key_count,
        orphan_count,
        invalid_value_count,
        projected_count_match,
    ) = row

    if returned_entity_kind != entity_kind:
        raise ValueError(
            "QA03_PROJECTED returned the wrong "
            "entity kind"
        )

    sql_input_count = int(
        sql_input_count
    )

    sql_excluded_count = int(
        sql_excluded_count
    )

    sql_expected_projected_count = int(
        sql_expected_projected_count
    )

    projected_count = int(
        projected_count
    )

    duplicate_key_count = int(
        duplicate_key_count
    )

    orphan_count = int(
        orphan_count
    )

    invalid_value_count = int(
        invalid_value_count
    )

    input_count_match = (
        actual_input_count
        == expected_input_count
    )

    expectation_consistent = (
        sql_input_count
        == actual_input_count
        and sql_excluded_count
        == excluded_count
        and sql_expected_projected_count
        == expected_projected_count
    )

    violations: list[str] = []

    if not input_count_match:
        violations.append(
            "input_count_mismatch"
        )

    if not expectation_consistent:
        violations.append(
            "expectation_mismatch"
        )

    if not projected_count_match:
        violations.append(
            "projected_count_mismatch"
        )

    if duplicate_key_count != 0:
        violations.append(
            "duplicate_key"
        )

    if orphan_count != 0:
        violations.append(
            "orphan"
        )

    if invalid_value_count != 0:
        violations.append(
            "invalid_value"
        )

    violation_count = len(
        violations
    )

    result = (
        "pass"
        if violation_count == 0
        else "block"
    )

    actual_metrics = {
        "input_count":
            actual_input_count,

        "excluded_count":
            excluded_count,

        "projected_count":
            projected_count,

        "duplicate_key_count":
            duplicate_key_count,

        "orphan_count":
            orphan_count,

        "invalid_value_count":
            invalid_value_count,
    }

    expected_metrics = {
        "input_count":
            expected_input_count,

        "excluded_count":
            excluded_count,

        "projected_count":
            expected_projected_count,

        "duplicate_key_count":
            0,

        "orphan_count":
            0,

        "invalid_value_count":
            0,
    }

    if result == "pass":
        resolution = (
            "Projection matches the independently "
            "derived frozen Raw and occurrence-scope "
            "expectations."
        )
    else:
        resolution = (
            "Projection or Raw coverage requires "
            "correction before the QA03 object "
            "can pass."
        )

    return {
        "rule_id":
            "QA03_PROJECTED",

        "object_key":
            f"resource:{resource_id}",

        "result":
            result,

        "affected_count":
            violation_count,

        "actual": {
            "evaluated_count":
                projected_count,

            "violation_count":
                violation_count,

            "metrics":
                actual_metrics,
        },

        "expected": {
            "evaluated_count":
                expected_projected_count,

            "violation_count":
                0,

            "metrics":
                expected_metrics,
        },

        "evidence": {
            "reason_codes":
                violations,

            "resolution":
                resolution,

            "references":
                references,

            "producer_version":
                PRODUCER_VERSION,
        },
    }


def run_qa03_resource(
    connection,
    manifest: dict,
    *,
    batch_id,
    resource_id: str,
) -> dict:
    """
    Convenience entry point for one QA03 object.

    Flow:

        frozen manifest + Raw
            -> derive expectation

        projected temp tables
            -> evaluate actual projection

        -> QA03 result object
    """

    expectation = derive_qa03_expectation(
        connection,
        manifest,
        resource_id=resource_id,
    )

    source = _manifest_source(
        manifest,
        expectation["source_id"],
    )

    release_scope = source[
        "release_scope"
    ]

    return evaluate_qa03_resource(
        connection,
        batch_id=batch_id,
        release_scope=release_scope,
        expectation=expectation,
    )
    
