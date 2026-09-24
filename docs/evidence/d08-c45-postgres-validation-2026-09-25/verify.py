#!/usr/bin/env python3
"""Run combined C04/C05 and D03-D08 acceptance in disposable containers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
POSTGRES_IMAGE = (
    "postgres@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67"
)
PYTHON_IMAGE = "python:3.12-slim-bookworm"
TESTS = tuple(
    ROOT / "tests" / name
    for name in (
        "test_c04_vic_projection.py",
        "test_c05_manifest.py",
        "test_c45_packaging.py",
        "test_c45_postgres.py",
        "test_d07_postgres.py",
        "test_d08_postgres.py",
        "test_d_c45_postgres.py",
    )
)
DEPLOY_SQL = (
    ROOT / "src/arsia_d05/sql/d05_trend.sql",
    ROOT / "src/arsia_d06/sql/d06_severity.sql",
    ROOT / "src/arsia_d07/sql/d07_map.sql",
    ROOT / "src/arsia_d08/sql/d08_units.sql",
)


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


def record(path: Path) -> dict[str, str]:
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}


def write(root: Path, name: str, value: object) -> None:
    (root / name).write_text(
        json.dumps(value, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    args = parser.parse_args()

    missing = [str(path) for path in (*TESTS, *DEPLOY_SQL) if not path.is_file()]
    if missing:
        parser.error("Missing combined acceptance input: " + ", ".join(missing))
    migrations = sorted((ROOT / "sql/migrations").glob("*.sql"))
    if [path.name[:3] for path in migrations] != [f"{value:03}" for value in range(1, 12)]:
        parser.error("Expected migrations 001 through 011")

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # This verifier also runs from a linked Windows worktree where the
    # elevated Docker process may not be allowed to traverse Git's shared
    # administrative directory. The caller supplies the two exact inputs.
    head = os.environ.get("ARSIA_D_HEAD", "144fb80e27e7004e5647cacbb245603f6f2d7d36")
    c_head = os.environ.get("ARSIA_C_HEAD", "ad8baeddd3f6d2eeccdc2e31bafd71b687ad4da8")
    d07_head = os.environ.get("ARSIA_D07_HEAD", "working-tree")
    d08_head = os.environ.get("ARSIA_D08_HEAD", "working-tree")
    status = ["temporary integration overlay; exact file hashes follow"]
    write(
        output,
        "inputs.json",
        {
            "head": head,
            "c_head": c_head,
            "d07_head": d07_head,
            "d08_head": d08_head,
            "working_tree": status,
            "postgres_image": POSTGRES_IMAGE,
            "python_image": PYTHON_IMAGE,
            "migrations": [record(path) for path in migrations],
            "deployment_sql": [record(path) for path in DEPLOY_SQL],
            "tests": [record(path) for path in TESTS],
        },
    )

    suffix = secrets.token_hex(6)
    network = f"arsia-cd-acceptance-{suffix}"
    database = f"arsia-cd-postgres-{suffix}"
    password = secrets.token_hex(24)
    network_started = False
    database_started = False
    try:
        run([args.docker, "pull", POSTGRES_IMAGE])
        run([args.docker, "pull", PYTHON_IMAGE])
        run([args.docker, "network", "create", network])
        network_started = True
        with tempfile.TemporaryDirectory(prefix="arsia-cd-acceptance-") as temporary:
            env_file = Path(temporary) / "postgres.env"
            env_file.write_text(
                "POSTGRES_USER=arsia_owner\n"
                "POSTGRES_DB=arsia\n"
                f"POSTGRES_PASSWORD={password}\n",
                encoding="utf-8",
            )
            run(
                [
                    args.docker,
                    "run",
                    "-d",
                    "--name",
                    database,
                    "--network",
                    network,
                    "--label",
                    "arsia.scope=c45-d03-d06-acceptance",
                    "--env-file",
                    str(env_file),
                    "--tmpfs",
                    "/var/lib/postgresql/data",
                    POSTGRES_IMAGE,
                    "postgres",
                    "-c",
                    "timezone=UTC",
                    "-c",
                    "log_timezone=UTC",
                ]
            )
            database_started = True

        for _ in range(150):
            ready = subprocess.run(
                [
                    args.docker,
                    "exec",
                    database,
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
            raise RuntimeError("PostgreSQL 16 did not become ready")

        def sql(statement: str) -> str:
            result = run(
                [
                    args.docker,
                    "exec",
                    "-i",
                    database,
                    "psql",
                    "-X",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-U",
                    "arsia_owner",
                    "-d",
                    "arsia",
                ],
                input=statement,
            )
            return result.stdout + result.stderr

        with (output / "database-setup.log").open("w", encoding="utf-8") as log:
            for migration in migrations:
                log.write(migration.name + "\n")
                log.write(sql(migration.read_text(encoding="utf-8")))
            log.write(sql(f"ALTER ROLE arsia_loader PASSWORD '{password}';"))
            for deployment in DEPLOY_SQL:
                log.write(deployment.name + "\n")
                log.write(sql(deployment.read_text(encoding="utf-8")))

        repository_mount = f"{ROOT}:/work:ro"
        evidence_mount = f"{output}:/evidence"
        dsn = (
            f"postgresql://arsia_loader:{password}@{database}:5432/arsia"
        )
        admin_dsn = (
            f"postgresql://arsia_owner:{password}@{database}:5432/arsia"
        )
        test_paths = " ".join(f"/tmp/repo/tests/{path.name}" for path in TESTS)
        container_command = (
            "mkdir -p /tmp/repo && cp -a /work/. /tmp/repo/ && "
            "python -m pip install --disable-pip-version-check --no-cache-dir "
            "-r /tmp/repo/requirements-dev.txt -r /tmp/repo/requirements-db.txt "
            "/tmp/repo && "
            "python -m pytest -q -p no:cacheprovider "
            f"{test_paths} --junitxml=/evidence/pytest.xml"
        )
        completed = subprocess.run(
            [
                args.docker,
                "run",
                "--rm",
                "--network",
                network,
                "-v",
                repository_mount,
                "-v",
                evidence_mount,
                "-e",
                f"ARSIA_TEST_DSN={dsn}",
                "-e",
                f"ARSIA_TEST_ADMIN_DSN={admin_dsn}",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                "-w",
                "/tmp",
                PYTHON_IMAGE,
                "sh",
                "-lc",
                container_command,
            ],
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        test_output = (completed.stdout + completed.stderr).replace(
            password, "[redacted]"
        )
        (output / "pytest.log").write_text(test_output, encoding="utf-8")
        print(test_output)

        environment = json.loads(
            run(
                [
                    args.docker,
                    "image",
                    "inspect",
                    POSTGRES_IMAGE,
                    PYTHON_IMAGE,
                ]
            ).stdout
        )
        write(
            output,
            "environment.json",
            {
                "docker": run(
                    [args.docker, "version", "--format", "{{json .}}"]
                ).stdout.strip(),
                "images": [
                    {
                        "id": image["Id"],
                        "repo_digests": image.get("RepoDigests", []),
                    }
                    for image in environment
                ],
            },
        )
        report = output / "pytest.xml"
        if not report.is_file():
            write(
                output,
                "summary.json",
                {"exit_code": completed.returncode, "report_created": False},
            )
            return completed.returncode or 1
        suites = ET.parse(report).getroot().findall("testsuite")
        totals = {
            key: sum(int(suite.attrib.get(key, "0")) for suite in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        result = completed.returncode or (
            1 if totals["failures"] or totals["errors"] or totals["skipped"] else 0
        )
        write(
            output,
            "summary.json",
            {
                **totals,
                "pytest_exit_code": completed.returncode,
                "exit_code": result,
                "postgresql_major": 16,
                "publication_performed": False,
            },
        )
        return result
    finally:
        cleanup: dict[str, object] = {
            "database_container_removed": False,
            "network_removed": False,
            "persistent_volume_created": False,
        }
        if database_started:
            subprocess.run(
                [args.docker, "rm", "-f", database], capture_output=True
            )
            cleanup["database_container_removed"] = True
        if network_started:
            subprocess.run(
                [args.docker, "network", "rm", network], capture_output=True
            )
            cleanup["network_removed"] = True
        write(output, "cleanup.json", cleanup)


if __name__ == "__main__":
    raise SystemExit(main())
