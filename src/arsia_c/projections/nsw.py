from __future__ import annotations

from pathlib import Path


NSW_CRASH_RESOURCE_ID = "official_nsw_crash"
NSW_TRAFFIC_UNIT_RESOURCE_ID = "official_nsw_traffic_unit"

SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw.sql"
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


def _load_sql() -> str:
    return SQL_PATH.read_text(encoding="utf-8")


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

    sql = _load_sql()

    cursor = connection.cursor()
    cursor.execute(
        sql,
        (
            crash_input["source_id"],
            crash_input["resource_id"],
            crash_input["file_sha256"],
            crash_input["parser_version"],
        ),
    )

    crash_rows = cursor.fetchall()

    # C03 transformation will be added next.
    # Keep the full Raw crash snapshot at this stage.
    # Do not filter occurrence year yet.

    _ = batch_id
    _ = unit_input
    _ = crash_rows
