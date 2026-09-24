from __future__ import annotations

from pathlib import Path
import json


QA03_SQL_PATH = (
    Path(__file__).resolve().parents[2]
    / "sql"
    / "qa"
    / "c10_qa03_projected.sql"
)

PRODUCER_VERSION = "c10-role-c-v0.1"


def _load_sql(path: Path) -> str:
    return path.read_text(
        encoding="utf-8"
    )


def evaluate_qa03_resource(
    connection,
    *,
    batch_id,
    source_id: str,
    release_scope: str,
    resource_id: str,
    entity_kind: str,
    input_count: int,
    excluded_count: int,
    references: list[dict] | None = None,
) -> dict:
    """
    Evaluate one QA03_PROJECTED object.

    input_count and excluded_count MUST be independently
    derived from the frozen Raw/source contract before
    calling this function.

    This function must not derive excluded_count from
    projected_count.
    """

    if entity_kind not in {
        "crash",
        "unit",
    }:
        raise ValueError(
            "QA03 entity_kind must be "
            "'crash' or 'unit'"
        )

    if input_count < 0:
        raise ValueError(
            "QA03 input_count cannot be negative"
        )

    if excluded_count < 0:
        raise ValueError(
            "QA03 excluded_count cannot be negative"
        )

    if excluded_count > input_count:
        raise ValueError(
            "QA03 excluded_count cannot exceed "
            "input_count"
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
        "input_count":
            input_count,
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
                json.dumps(
                    params
                ),
            ),
        )

        row = cursor.fetchone()

    if row is None:
        raise ValueError(
            "QA03_PROJECTED returned no result"
        )

    (
        returned_entity_kind,
        actual_input_count,
        actual_excluded_count,
        expected_projected_count,
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

    metrics = {
        "input_count":
            actual_input_count,
        "excluded_count":
            actual_excluded_count,
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
            input_count,
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

    violations = []

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

    object_key = (
        f"resource:{resource_id}"
    )

    return {
        "rule_id":
            "QA03_PROJECTED",

        "object_key":
            object_key,

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
                metrics,
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
                (
                    "projection matches independently "
                    "derived Raw/scope expectations"
                    if result == "pass"
                    else
                    "projection requires correction "
                    "before publication"
                ),
            "references":
                list(
                    references or []
                ),
            "producer_version":
                PRODUCER_VERSION,
        },
    }
