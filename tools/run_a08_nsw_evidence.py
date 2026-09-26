#!/usr/bin/env python3
"""Temporarily load the pinned NSW pair, run A08 SQL and roll everything back."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re

import psycopg

from arsia_ingest.raw_load import load_prepared


QUERY_MARKER = re.compile(r"^-- name: ([a-z][a-z0-9_]*)\s*$", re.MULTILINE)
SOURCE = {
    "source_id": "official_nsw",
    "jurisdiction_code": "NSW",
    "source_name": "NSW Road Crash Data",
    "publisher": "Transport for NSW",
}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def json_safe(value):
    """Preserve exact PostgreSQL values in standard JSON-compatible types."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def split_queries(path: Path) -> list[tuple[str, str]]:
    sql = path.read_text(encoding="utf-8")
    markers = list(QUERY_MARKER.finditer(sql))
    if not markers:
        raise ValueError("The SQL file has no -- name: query markers")
    queries = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(sql)
        statement = sql[marker.end():end].strip()
        if not statement:
            raise ValueError(f"Empty SQL statement: {marker.group(1)}")
        queries.append((marker.group(1), statement))
    names = [name for name, _ in queries]
    if len(names) != len(set(names)):
        raise ValueError("SQL query names must be unique")
    return queries


def selected_counts(connection) -> dict[str, int]:
    with connection.cursor() as cursor:
        source_rows = cursor.execute(
            "SELECT count(*) FROM meta.source WHERE source_id = 'official_nsw'"
        ).fetchone()[0]
        resource_rows = cursor.execute(
            """SELECT count(*) FROM meta.resource
               WHERE resource_id IN (
                   'official_nsw_crash', 'official_nsw_traffic_unit'
               )"""
        ).fetchone()[0]
        raw_rows = cursor.execute(
            """SELECT count(*) FROM raw.record
               WHERE source_id = 'official_nsw'
                 AND resource_id IN (
                     'official_nsw_crash', 'official_nsw_traffic_unit'
                 )"""
        ).fetchone()[0]
    return {
        "source_rows": source_rows,
        "resource_rows": resource_rows,
        "raw_rows": raw_rows,
    }


def database_details(connection) -> dict:
    with connection.cursor() as cursor:
        row = cursor.execute(
            """SELECT
                   current_user,
                   current_setting('server_encoding'),
                   current_setting('TimeZone'),
                   rolsuper
               FROM pg_roles
               WHERE rolname = current_user"""
        ).fetchone()
    if connection.info.server_version // 10000 != 16:
        raise RuntimeError("A08 evidence requires PostgreSQL 16")
    if row != ("arsia_loader", "UTF8", "UTC", False):
        raise RuntimeError(
            "A08 evidence requires restricted arsia_loader, UTF8 and UTC"
        )
    return {
        "postgresql_major": 16,
        "server_version": connection.info.server_version,
        "current_user": row[0],
        "server_encoding": row[1],
        "timezone": row[2],
        "superuser": row[3],
    }


def execute_queries(connection, queries: list[tuple[str, str]]) -> list[dict]:
    results = []
    with connection.cursor() as cursor:
        for name, statement in queries:
            print(f"[A08] running query: {name}", flush=True)
            cursor.execute(statement)
            columns = (
                [column.name for column in cursor.description]
                if cursor.description is not None
                else []
            )
            rows = cursor.fetchall() if columns else []
            results.append(
                {
                    "name": name,
                    "status": cursor.statusmessage,
                    "columns": columns,
                    "rows": [json_safe(row) for row in rows],
                }
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--sql",
        type=Path,
        default=Path("sql/evidence/a08_nsw_source_queries.sql"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dsn = os.environ.get("ARSIA_TEST_DSN")
    if not dsn:
        parser.error("Set ARSIA_TEST_DSN for the restricted arsia_loader role")
    run_dir = args.run_dir.resolve()
    sql_path = args.sql.resolve()
    output = args.output.resolve()
    if output.exists():
        parser.error(f"Refusing to overwrite existing evidence: {output}")

    run = read_json(run_dir / "run.json")
    files = read_json(run_dir / "files.json")["files"]
    queries = split_queries(sql_path)
    evidence = None

    with psycopg.connect(dsn, autocommit=False) as connection:
        database = database_details(connection)
        baseline = selected_counts(connection)
        if any(baseline.values()):
            raise RuntimeError(
                "A08 requires a clean official_nsw baseline; no writes were made"
            )
        try:
            loaded_rows = 0

            def report_progress(_record, _result):
                nonlocal loaded_rows
                loaded_rows += 1
                if loaded_rows % 10000 == 0:
                    print(
                        f"[A08] loaded {loaded_rows}/{run['raw_count']} Raw rows",
                        flush=True,
                    )

            print(
                f"[A08] loading {run['raw_count']} prepared Raw rows",
                flush=True,
            )
            loaded = load_prepared(
                connection,
                run_dir,
                [SOURCE],
                on_record=report_progress,
            )
            print(f"[A08] loaded {loaded.raw_count} Raw rows", flush=True)
            results = execute_queries(connection, queries)
            evidence = {
                "evidence_version": "a08-nsw-query-evidence-v1",
                "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "scope": (
                    "Temporary official NSW Raw load and source queries only; "
                    "no contract confirmation, build or publication"
                ),
                "prepared_run": {
                    "run_id": run["run_id"],
                    "dataset_kind": run["dataset_kind"],
                    "status": run["status"],
                    "raw_count": run["raw_count"],
                    "files": files,
                },
                "database": database,
                "sql": {
                    "path": str(args.sql),
                    "sha256": sha256(sql_path),
                },
                "load": asdict(loaded),
                "queries": results,
                "rollback": {
                    "baseline": baseline,
                    "performed": True,
                },
            }
        finally:
            print("[A08] rolling back temporary Raw rows", flush=True)
            connection.rollback()

        after = selected_counts(connection)
        if after != baseline:
            raise RuntimeError(
                f"Rollback did not restore the selected baseline: {after}"
            )
        evidence["rollback"]["after"] = after
        evidence["rollback"]["restored"] = True
        print("[A08] rollback restored the clean baseline", flush=True)
        connection.rollback()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
