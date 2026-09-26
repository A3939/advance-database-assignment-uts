#!/usr/bin/env python3
"""Rebuild ARSIA's database schema in a disposable PostgreSQL 16 container."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
IMAGE = "postgres:16-bookworm@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67"
CONTRACT_PATH = ROOT / "config/schema-v1.1.json"
AUDIT_PATH = ROOT / "sql/tests/a03_database_roles.sql"
DEFAULT_DICTIONARY = ROOT.parent / "ARSIA-Team-Handoff-EN 2/02-Database-Field-Dictionary.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(arguments, **kwargs):
    return subprocess.run(
        [str(argument) for argument in arguments],
        check=True,
        capture_output=True,
        text=True,
        **kwargs,
    )


def find_migrations() -> list[Path]:
    migrations = sorted((ROOT / "sql/migrations").glob("*.sql"))
    expected = [f"{number:03}" for number in range(1, 12)]
    if [path.name[:3] for path in migrations] != expected:
        raise ValueError("Expected exactly migrations 001 through 011")
    return migrations


def container_arguments(name: str, env_file: str) -> list[str]:
    return [
        "run",
        "-d",
        "--name",
        name,
        "--label",
        "arsia.scope=a09-cold-start",
        "--env-file",
        env_file,
        "-p",
        "127.0.0.1::5432",
        "--tmpfs",
        "/var/lib/postgresql/data",
        IMAGE,
        "postgres",
        "-c",
        "timezone=UTC",
        "-c",
        "log_timezone=UTC",
    ]


def psql(docker: str, name: str, statement: str) -> str:
    result = run(
        [
            docker,
            "exec",
            "-i",
            name,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "arsia_owner",
            "-d",
            "arsia",
            "-At",
        ],
        input=statement,
    )
    return (result.stdout + result.stderr).strip()


def json_query(docker: str, name: str, statement: str):
    output = psql(docker, name, statement)
    if not output:
        raise ValueError("Catalog query returned no JSON")
    return json.loads(output.splitlines()[-1])


def catalog_columns(docker: str, name: str):
    return json_query(
        docker,
        name,
        """
        SELECT coalesce(jsonb_object_agg(table_name, columns ORDER BY table_name), '{}'::jsonb)
        FROM (
            SELECT n.nspname || '.' || c.relname AS table_name,
                   jsonb_agg(
                       jsonb_build_array(
                           a.attname,
                           pg_catalog.format_type(a.atttypid, a.atttypmod),
                           NOT a.attnotnull
                       ) ORDER BY a.attnum
                   ) AS columns
            FROM pg_catalog.pg_class AS c
            JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_attribute AS a ON a.attrelid = c.oid
            WHERE n.nspname IN ('meta', 'raw', 'rv', 'canonical', 'dw', 'qa')
              AND c.relkind = 'r'
              AND a.attnum > 0
              AND NOT a.attisdropped
            GROUP BY n.nspname, c.relname
        ) AS inventory;
        """,
    )


def catalog_constraint_counts(docker: str, name: str):
    return json_query(
        docker,
        name,
        """
        SELECT jsonb_build_object(
            'check', count(*) FILTER (WHERE c.contype = 'c'),
            'foreign_key', count(*) FILTER (WHERE c.contype = 'f'),
            'primary_key', count(*) FILTER (WHERE c.contype = 'p'),
            'unique', count(*) FILTER (WHERE c.contype = 'u')
        )
        FROM pg_catalog.pg_constraint AS c
        JOIN pg_catalog.pg_namespace AS n ON n.oid = c.connamespace
        WHERE n.nspname IN ('meta', 'raw', 'rv', 'canonical', 'dw', 'qa');
        """,
    )


def catalog_roles(docker: str, name: str):
    return json_query(
        docker,
        name,
        """
        SELECT jsonb_object_agg(rolname, jsonb_build_object(
            'can_login', rolcanlogin,
            'superuser', rolsuper,
            'create_database', rolcreatedb,
            'create_role', rolcreaterole,
            'replication', rolreplication,
            'bypass_rls', rolbypassrls
        ) ORDER BY rolname)
        FROM pg_catalog.pg_roles
        WHERE rolname IN ('arsia_loader', 'arsia_migrator', 'arsia_reader');
        """,
    )


def catalog_schema_owners(docker: str, name: str):
    return json_query(
        docker,
        name,
        """
        SELECT jsonb_object_agg(n.nspname, pg_get_userbyid(n.nspowner) ORDER BY n.nspname)
        FROM pg_catalog.pg_namespace AS n
        WHERE n.nspname IN ('meta', 'raw', 'rv', 'canonical', 'dw', 'qa', 'published');
        """,
    )


def catalog_function(docker: str, name: str):
    return json_query(
        docker,
        name,
        """
        SELECT jsonb_build_object(
            'identity', p.oid::regprocedure::text,
            'owner', pg_get_userbyid(p.proowner),
            'volatility', p.provolatile,
            'parallel', p.proparallel,
            'loader_can_execute', has_function_privilege(
                'arsia_loader', p.oid, 'EXECUTE'
            ),
            'reader_can_execute', has_function_privilege(
                'arsia_reader', p.oid, 'EXECUTE'
            )
        )
        FROM pg_catalog.pg_proc AS p
        JOIN pg_catalog.pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'rv' AND p.proname = 'encode_business_key';
        """,
    )


def verify_catalog(contract, actual):
    expected_tables = contract["tables"]
    if actual["tables"] != expected_tables:
        expected_names = set(expected_tables)
        actual_names = set(actual["tables"])
        raise AssertionError(
            "Schema columns differ from v1.1 contract; "
            f"missing={sorted(expected_names - actual_names)}, "
            f"extra={sorted(actual_names - expected_names)}"
        )
    if actual["constraint_counts"] != contract["constraint_counts"]:
        raise AssertionError("Constraint counts differ from v1.1 contract")
    if actual["schemas"] != contract["schemas"]:
        raise AssertionError("Schema list differs from v1.1 contract")
    expected_owners = {schema: "arsia_migrator" for schema in contract["schemas"]}
    expected_owners["published"] = "arsia_migrator"
    if actual["schema_owners"] != expected_owners:
        raise AssertionError("Schema owners differ from the A03 role model")
    expected_roles = {
        "arsia_loader": {
            "can_login": True,
            "superuser": False,
            "create_database": False,
            "create_role": False,
            "replication": False,
            "bypass_rls": False,
        },
        "arsia_migrator": {
            "can_login": False,
            "superuser": False,
            "create_database": False,
            "create_role": False,
            "replication": False,
            "bypass_rls": False,
        },
        "arsia_reader": {
            "can_login": True,
            "superuser": False,
            "create_database": False,
            "create_role": False,
            "replication": False,
            "bypass_rls": False,
        },
    }
    if actual["roles"] != expected_roles:
        raise AssertionError("Database roles differ from the A03 role model")
    expected_function = {
        "identity": "rv.encode_business_key(text[])",
        "owner": "arsia_migrator",
        "volatility": "i",
        "parallel": "s",
        "loader_can_execute": True,
        "reader_can_execute": False,
    }
    if actual["business_key_function"] != expected_function:
        raise AssertionError("Business-key function metadata differs from A05/A09")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    parser.add_argument("--dictionary", type=Path, default=DEFAULT_DICTIONARY)
    args = parser.parse_args()

    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12")
    output = args.output.resolve()
    if output.exists():
        parser.error(f"Output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    migrations = find_migrations()
    dictionary = args.dictionary.resolve()
    if not dictionary.is_file():
        parser.error("The v1.1 field dictionary is required for this recorded A09 run")
    dictionary_sha = digest(dictionary)
    if dictionary_sha != contract["dictionary"]["sha256"]:
        parser.error("The field dictionary SHA256 does not match schema-v1.1.json")

    name = "arsia-a09-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(30)
    started = False
    evidence = {
        "contract": "a09-cold-start-evidence-v1",
        "status": "failed",
        "started_at": utc_now(),
        "finished_at": None,
        "scope": {
            "executed": "Fresh PostgreSQL 16 database component through migrations 001-011",
            "not_executed": "Complete platform AT17, official/full-scale data, publication and remaining C/D/E modules",
        },
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "image": IMAGE,
            "temporary_storage": True,
            "persistent_volume_created": False,
        },
        "inputs": {
            "schema_contract": {
                "path": str(CONTRACT_PATH.relative_to(ROOT)),
                "sha256": digest(CONTRACT_PATH),
            },
            "dictionary": {
                "path": str(dictionary),
                "sha256": dictionary_sha,
            },
            "migrations": [
                {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
                for path in migrations
            ],
            "permission_audit": {
                "path": str(AUDIT_PATH.relative_to(ROOT)),
                "sha256": digest(AUDIT_PATH),
            },
            "git_head": run(["git", "-C", ROOT, "rev-parse", "HEAD"]).stdout.strip(),
            "working_tree": run(["git", "-C", ROOT, "status", "--short"]).stdout.splitlines(),
        },
        "migration_results": [],
        "checks": {},
        "cleanup": {
            "container_removed": False,
            "persistent_volume_created": False,
        },
        "error": None,
    }

    try:
        with tempfile.TemporaryDirectory(prefix="arsia-a09-") as temporary:
            env_file = Path(temporary) / "postgres.env"
            env_file.write_text(
                "POSTGRES_USER=arsia_owner\n"
                "POSTGRES_DB=arsia\n"
                f"POSTGRES_PASSWORD={password}\n",
                encoding="utf-8",
            )
            env_file.chmod(0o600)
            run([args.docker, *container_arguments(name, str(env_file))])
            started = True

        for _ in range(150):
            ready = subprocess.run(
                [
                    args.docker,
                    "exec",
                    name,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "arsia_owner",
                    "-d",
                    "arsia",
                ],
                capture_output=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("PostgreSQL did not become ready")

        evidence["environment"]["postgresql"] = psql(
            args.docker,
            name,
            "SELECT version(); SELECT current_setting('server_encoding'); SELECT current_setting('TimeZone');",
        ).splitlines()

        for migration in migrations:
            output_text = psql(args.docker, name, migration.read_text(encoding="utf-8"))
            evidence["migration_results"].append(
                {
                    "path": str(migration.relative_to(ROOT)),
                    "sha256": digest(migration),
                    "status": "applied",
                    "last_message": output_text.splitlines()[-1] if output_text else "",
                }
            )

        actual = {
            "schemas": sorted(
                json_query(
                    args.docker,
                    name,
                    """
                    SELECT jsonb_agg(nspname ORDER BY nspname)
                    FROM pg_catalog.pg_namespace
                    WHERE nspname IN ('meta', 'raw', 'rv', 'canonical', 'dw', 'qa');
                    """,
                )
            ),
            "tables": catalog_columns(args.docker, name),
            "constraint_counts": catalog_constraint_counts(args.docker, name),
            "schema_owners": catalog_schema_owners(args.docker, name),
            "roles": catalog_roles(args.docker, name),
            "business_key_function": catalog_function(args.docker, name),
        }
        verify_catalog(contract, actual)
        evidence["checks"]["catalog"] = {
            "status": "passed",
            "table_count": len(actual["tables"]),
            "field_count": sum(len(columns) for columns in actual["tables"].values()),
            "constraint_counts": actual["constraint_counts"],
            "schemas": actual["schemas"],
            "schema_owners": actual["schema_owners"],
            "roles": actual["roles"],
            "business_key_function": actual["business_key_function"],
            "tables": actual["tables"],
        }

        audit_output = psql(args.docker, name, AUDIT_PATH.read_text(encoding="utf-8"))
        evidence["checks"]["permission_audit"] = {
            "status": "passed",
            "last_message": audit_output.splitlines()[-1] if audit_output else "",
        }

        smoke = json_query(
            args.docker,
            name,
            """
            SELECT jsonb_build_object(
                'crash_key', rv.encode_business_key('0001'),
                'unit_key', rv.encode_business_key('0001', '01'),
                'map_constraint', pg_get_constraintdef(oid)
            )
            FROM pg_catalog.pg_constraint
            WHERE conname = 'canonical_crash_map_eligibility_valid';
            """,
        )
        if smoke["crash_key"] != '["0001"]' or smoke["unit_key"] != '["0001", "01"]':
            raise AssertionError("Business-key smoke values changed")
        if "location_record_id IS NOT NULL" not in smoke["map_constraint"]:
            raise AssertionError("Migration 011 map constraint is not active")
        evidence["checks"]["migration_011_smoke"] = {"status": "passed", **smoke}

        row_counts = json_query(
            args.docker,
            name,
            """
            SELECT jsonb_object_agg(table_name, row_count ORDER BY table_name)
            FROM (
                SELECT format('%I.%I', schemaname, relname) AS table_name,
                       n_live_tup::bigint AS row_count
                FROM pg_catalog.pg_stat_user_tables
                WHERE schemaname IN ('meta', 'raw', 'rv', 'canonical', 'dw', 'qa')
            ) AS counts;
            """,
        )
        if any(row_counts.values()):
            raise AssertionError("A fresh schema unexpectedly contains application rows")
        evidence["checks"]["empty_schema"] = {"status": "passed", "row_counts": row_counts}
        evidence["status"] = "passed"
    except Exception as error:  # Evidence must survive a failed diagnostic run.
        evidence["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if started:
            removal = subprocess.run(
                [args.docker, "rm", "-f", name],
                capture_output=True,
                text=True,
            )
            evidence["cleanup"]["container_removed"] = removal.returncode == 0
            if removal.returncode != 0 and evidence["error"] is None:
                evidence["error"] = {
                    "type": "CleanupError",
                    "message": removal.stderr.strip(),
                }
                evidence["status"] = "failed"
        evidence["finished_at"] = utc_now()
        serialized = json.dumps(evidence, indent=2, ensure_ascii=False).replace(password, "[redacted]")
        output.write_text(serialized + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "status": evidence["status"],
                "output": str(output),
                "migrations_applied": len(evidence["migration_results"]),
                "catalog": evidence["checks"].get("catalog", {}),
                "cleanup": evidence["cleanup"],
                "error": evidence["error"],
            },
            indent=2,
        )
    )
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
