from __future__ import annotations

from pathlib import Path


NSW_CRASH_RESOURCE_ID = "official_nsw_crash"
NSW_TRAFFIC_UNIT_RESOURCE_ID = "official_nsw_traffic_unit"

CRASH_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw.sql"
)

TRAFFIC_UNIT_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_traffic_unit.sql"
)

RELATIONSHIP_SQL_PATH = (
    Path(__file__).resolve().parents[3]
    / "sql"
    / "projections"
    / "c03_nsw_relationship_check.sql"
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

crash_sql = _load_sql(CRASH_SQL_PATH)
traffic_unit_sql = _load_sql(TRAFFIC_UNIT_SQL_PATH)

cursor = connection.cursor()

cursor.execute(
    crash_sql,
    (
        crash_input["source_id"],
        crash_input["resource_id"],
        crash_input["file_sha256"],
        crash_input["parser_version"],
    ),
)
crash_rows = cursor.fetchall()

cursor.execute(
    traffic_unit_sql,
    (
        unit_input["source_id"],
        unit_input["resource_id"],
        unit_input["file_sha256"],
        unit_input["parser_version"],
    ),
)
traffic_unit_rows = cursor.fetchall()

traffic_unit_sql = _load_sql(TRAFFIC_UNIT_SQL_PATH)

cursor.execute(
    traffic_unit_sql,
    (
        unit_input["source_id"],
        unit_input["resource_id"],
        unit_input["file_sha256"],
        unit_input["parser_version"],
    ),
)

traffic_unit_rows = cursor.fetchall()

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

    # C03 transformation will be added next.
    # Keep the full Raw crash snapshot at this stage.
    # Do not filter occurrence year yet.

_ = batch_id
_ = crash_rows
_ = traffic_unit_rows
_ = relationship_counts
