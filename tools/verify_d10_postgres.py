#!/usr/bin/env python3
"""Execute D10 against real QLD rows in a disposable PostgreSQL 16 database."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
from datetime import datetime, timezone
from uuid import UUID, uuid5
import zipfile

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_IMAGE = (
    "postgres@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67"
)
MEMBER = "raw/qld_crash_locations.csv"
FILE_SHA256 = "975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704"
BATCH_ID = "d6f0e958-7c94-4f2f-ba85-9d44e597cc02"
RELEASE_SCOPE = "qld_pinned_2020_2024_v1"
RAW_NAMESPACE = UUID("fd7f70f0-6a03-5686-a761-cc41850b5f73")


def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        **kwargs,
    )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def member_digest(archive: Path) -> str:
    result = hashlib.sha256()
    with zipfile.ZipFile(archive) as source, source.open(MEMBER) as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
    return result.hexdigest()


def wait_for_postgres(docker: str, container: str) -> None:
    for _ in range(180):
        result = subprocess.run(
            [docker, "exec", container, "pg_isready", "-U", "arsia_owner", "-d", "arsia"],
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(0.25)
    raise RuntimeError("PostgreSQL 16 did not become ready")


def load_raw(connection: psycopg.Connection, archive: Path) -> int:
    statement = """
        COPY raw.record (
          raw_record_id, resource_id, source_id, file_sha256,
          parser_version, row_locator, payload
        ) FROM STDIN
    """
    count = 0
    with zipfile.ZipFile(archive) as source, source.open(MEMBER) as binary:
        text = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        with connection.cursor() as cursor, cursor.copy(statement) as copy:
            for count, payload in enumerate(reader, start=1):
                locator = f"csv:{count}"
                raw_id = uuid5(RAW_NAMESPACE, f"{FILE_SHA256}|{locator}")
                copy.write_row(
                    (
                        raw_id,
                        "official_qld_crash",
                        "official_qld",
                        FILE_SHA256,
                        "csv-native-v1",
                        locator,
                        Jsonb(payload),
                    )
                )
    connection.commit()
    return count


def install_validation_projection(connection: psycopg.Connection) -> None:
    """Install the exact D10 Q8 boundary without claiming a new publication."""
    statement = f"""
    INSERT INTO meta.source (source_id, jurisdiction_code, source_name, publisher)
    VALUES ('official_qld', 'QLD', 'Queensland Road Crash Locations',
            'Queensland Department of Transport and Main Roads');
    INSERT INTO meta.resource (resource_id, source_id, resource_role, entity_kind)
    VALUES ('official_qld_crash', 'official_qld', 'crash', 'crash');
    INSERT INTO meta.batch (
      batch_id, dataset_kind, input_fingerprint, manifest, status, finished_at
    ) VALUES (
      '{BATCH_ID}'::uuid, 'official', repeat('a', 64),
      '{{"validation_scope":"d10_sql_execution_only"}}'::jsonb,
      'succeeded', now()
    );
    """
    connection.execute(statement, prepare=False)
    connection.commit()


def project_analysis_rows(connection: psycopg.Connection) -> None:
    month_case = """
      CASE btrim(payload ->> 'Crash_Month')
        WHEN 'January' THEN 1 WHEN 'February' THEN 2 WHEN 'March' THEN 3
        WHEN 'April' THEN 4 WHEN 'May' THEN 5 WHEN 'June' THEN 6
        WHEN 'July' THEN 7 WHEN 'August' THEN 8 WHEN 'September' THEN 9
        WHEN 'October' THEN 10 WHEN 'November' THEN 11 WHEN 'December' THEN 12
      END
    """
    base = f"""
      source_id = 'official_qld'
      AND resource_id = 'official_qld_crash'
      AND file_sha256 = '{FILE_SHA256}'
      AND parser_version = 'csv-native-v1'
      AND (payload ->> 'Crash_Year')::integer BETWEEN 2020 AND 2024
    """
    key = "rv.encode_business_key(payload ->> 'Crash_Ref_Number')"
    statement = f"""
    INSERT INTO rv.hub_crash (
      source_id, release_scope, crash_key, first_seen_batch_id
    )
    SELECT source_id, '{RELEASE_SCOPE}', {key}, '{BATCH_ID}'::uuid
    FROM raw.record WHERE {base};

    INSERT INTO rv.sat_crash (
      batch_id, source_id, release_scope, crash_key, raw_record_id, attributes
    )
    SELECT '{BATCH_ID}'::uuid, source_id, '{RELEASE_SCOPE}', {key},
           raw_record_id, payload
    FROM raw.record WHERE {base};

    INSERT INTO canonical.crash (
      batch_id, source_id, release_scope, crash_key, raw_record_id,
      occurrence_year, occurrence_month, occurrence_date, date_precision,
      severity_raw, severity_code, severity_definition_version,
      is_fatal_crash, fatality_count, casualty_count,
      fatal_crash_eligible, fatality_eligible, casualty_eligible,
      latitude, longitude, location_crs, map_eligible, location_record_id,
      quality_notes
    )
    SELECT '{BATCH_ID}'::uuid, source_id, '{RELEASE_SCOPE}', {key}, raw_record_id,
           (payload ->> 'Crash_Year')::integer, {month_case}, NULL, 'month',
           payload ->> 'Crash_Severity', payload ->> 'Crash_Severity',
           'qld-native-severity-v1',
           (payload ->> 'Crash_Severity') = 'Fatal',
           (payload ->> 'Count_Casualty_Fatality')::integer,
           (payload ->> 'Count_Casualty_Total')::integer,
           true, true, true,
           NULL, NULL, NULL, false, NULL,
           '{{"validation_projection":"D10 PostgreSQL execution"}}'::jsonb
    FROM raw.record WHERE {base};
    """
    connection.execute(statement, prepare=False)
    connection.commit()


def execute_d10(connection: psycopg.Connection, query_path: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    with connection.cursor() as cursor:
        cursor.execute(query_path.read_text(encoding="utf-8"), prepare=False)
        while True:
            if cursor.description:
                columns = [column.name for column in cursor.description]
                rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
                results.append({"columns": columns, "rows": rows})
            if not cursor.nextset():
                break
    return results


def validate(results: list[dict[str, object]]) -> None:
    if len(results) != 8:
        raise AssertionError(f"expected eight D10 result sets, got {len(results)}")
    key = results[0]["rows"][0]
    assert key == {
        "full_source_rows": 415407,
        "blank_keys": 0,
        "distinct_nonblank_keys": 415407,
        "duplicate_or_blank_keys": 0,
        "analysis_rows": 66624,
    }
    months = results[2]["rows"]
    assert len(months) == 60
    assert sum(row["crash_count"] for row in months) == 66624
    severity = {row["native_value"]: row["crash_count"] for row in results[3]["rows"]}
    assert severity == {
        "Fatal": 1304,
        "Hospitalisation": 31922,
        "Medical treatment": 22730,
        "Minor injury": 10668,
        "Property damage only": 0,
        "__MISSING__": 0,
    }
    casualty = results[4]["rows"][0]
    assert casualty == {
        "rows_with_missing_count": 0,
        "rows_with_invalid_count": 0,
        "component_mismatch_rows": 0,
        "fatality_sum": 1424,
        "casualty_total_sum": 88609,
    }
    units = {row["category"]: row for row in results[5]["rows"]}
    assert units["Count_Unit_Car"]["aggregate_sum"] == 102555
    assert all(row["missing_rows"] == row["invalid_rows"] == 0 for row in units.values())
    location = results[6]["rows"][0]
    assert location["analysis_rows"] == location["native_coordinate_rows"] == 66624
    assert location["missing_coordinate_rows"] == 0
    assert location["published_map_available"] is False
    published = results[7]["rows"][0]
    assert published == {
        "crash_count": 66624,
        "published_map_count": 0,
        "published_unmapped_count": 66624,
        "canonical_unit_count": 0,
    }


def json_value(value: object) -> object:
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    return str(value) if not isinstance(value, (str, int, float, bool, type(None))) else value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", required=True)
    args = parser.parse_args()

    archive = args.archive.resolve()
    output = args.output.resolve()
    query = ROOT / "sql/d10_qld_source_evidence.sql"
    migrations = sorted((ROOT / "sql/migrations").glob("*.sql"))
    if [path.name[:3] for path in migrations] != [f"{number:03}" for number in range(1, 12)]:
        parser.error("expected migrations 001 through 011")
    if sys.version_info[:2] != (3, 12):
        parser.error(f"Python 3.12 required, got {sys.version.split()[0]}")
    if member_digest(archive) != FILE_SHA256:
        parser.error("QLD source SHA-256 does not match the frozen contract")

    container = "arsia-d10-pg16-" + secrets.token_hex(6)
    password = secrets.token_hex(24)
    started = time.perf_counter()
    try:
        run([args.docker, "pull", POSTGRES_IMAGE])
        run([
            args.docker, "run", "-d", "--name", container,
            "--label", "arsia.scope=d10-postgres16-validation",
            "-e", "POSTGRES_USER=arsia_owner", "-e", "POSTGRES_DB=arsia",
            "-e", f"POSTGRES_PASSWORD={password}",
            "-p", "127.0.0.1::5432", "--tmpfs", "/var/lib/postgresql/data",
            POSTGRES_IMAGE, "postgres", "-c", "timezone=UTC", "-c", "log_timezone=UTC",
        ])
        wait_for_postgres(args.docker, container)
        port = run([
            args.docker, "port", container, "5432/tcp"
        ]).stdout.strip().rsplit(":", 1)[-1]
        owner_dsn = f"postgresql://arsia_owner:{password}@127.0.0.1:{port}/arsia"

        with psycopg.connect(owner_dsn, autocommit=True) as owner:
            for migration in migrations:
                owner.execute(migration.read_text(encoding="utf-8"), prepare=False)
            owner.execute(
                sql.SQL("ALTER ROLE arsia_loader PASSWORD {}").format(sql.Literal(password))
            )
        loader_dsn = f"postgresql://arsia_loader:{password}@127.0.0.1:{port}/arsia"
        with psycopg.connect(owner_dsn) as owner:
            install_validation_projection(owner)
            raw_rows = load_raw(owner, archive)
            project_analysis_rows(owner)
        with psycopg.connect(loader_dsn, autocommit=True) as loader:
            server_version = loader.execute("SHOW server_version").fetchone()[0]
            results = execute_d10(loader, query)
            validate(results)
            temp_after_rollback = loader.execute(
                "SELECT to_regclass('pg_temp.d10_qld_native')"
            ).fetchone()[0]
            assert temp_after_rollback is None

        docker_version = json.loads(
            run([args.docker, "version", "--format", "{{json .}}"] ).stdout
        )
        image = json.loads(run([args.docker, "image", "inspect", POSTGRES_IMAGE]).stdout)[0]
        head = run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).stdout.strip()
        receipt = {
            "evidence_version": "d10-postgresql16-validation-v1",
            "status": "passed",
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "scope": (
                "Disposable PostgreSQL SQL-execution acceptance using every native QLD row; "
                "the Canonical Q8 boundary is reconstructed from those rows solely to execute "
                "the committed query and is not a shared or public release."
            ),
            "environment": {
                "python": sys.version.split()[0],
                "psycopg": psycopg.__version__,
                "postgresql": server_version,
                "postgres_image": POSTGRES_IMAGE,
                "postgres_image_id": image["Id"],
                "docker_client": docker_version["Client"]["Version"],
                "docker_server": docker_version["Server"]["Version"],
            },
            "inputs": {
                "commit": head,
                "query": {"path": query.relative_to(ROOT).as_posix(), "sha256": digest(query)},
                "file_sha256": FILE_SHA256,
                "raw_rows_loaded": raw_rows,
                "migrations": [
                    {"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path)}
                    for path in migrations
                ],
            },
            "validation": {
                "result_sets": json_value(results),
                "result_set_count": len(results),
                "temporary_view_after_rollback": temp_after_rollback,
                "permanent_objects_created_by_d10_sql": 0,
                "assertions": "all passed",
            },
            "duration_seconds": round(time.perf_counter() - started, 3),
            "publication_performed": False,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "passed", "output": str(output), "postgresql": server_version,
            "python": sys.version.split()[0], "psycopg": psycopg.__version__,
            "raw_rows": raw_rows, "analysis_rows": 66624,
            "duration_seconds": receipt["duration_seconds"],
        }))
        return 0
    finally:
        subprocess.run([args.docker, "rm", "-f", container], capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
