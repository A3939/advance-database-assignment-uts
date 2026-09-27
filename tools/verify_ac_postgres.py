#!/usr/bin/env python3
"""Check the installed B/A/C package in a disposable PostgreSQL 16 database."""
import argparse
import hashlib
import importlib
import importlib.metadata
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

IMAGE = "postgres@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67"
ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "test_raw_load_postgres.py", "test_input_qa_postgres.py", "test_runner_postgres.py",
    "test_vault_load_postgres.py", "test_business_key_postgres.py",
    "test_canonical_constraints_postgres.py", "test_c03_nsw_projection.py",
    "test_c03_nsw_postgres.py", "test_c03_packaging.py", "test_c09_canonical.py",
    "test_c09_postgres.py", "test_c09_acceptance_postgres.py", "test_d02.py",
    "test_d02_postgres.py", "test_ac_inventory.py", "test_ac_integration_postgres.py",
    "test_b10_lifecycle_postgres.py", "test_runner.py", "test_recovery.py",
)
TABLES = (
    "meta.source", "meta.resource", "meta.batch", "meta.current_release", "raw.record",
    "rv.hub_crash", "rv.hub_unit", "rv.sat_crash", "rv.sat_unit", "rv.link_crash_unit",
    "canonical.crash", "canonical.unit", "dw.dim_source", "dw.dim_month",
    "dw.dim_severity", "dw.fact_crash", "qa.check_result",
)


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(root, name, value):
    (root / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def record(path):
    return {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}


def check_install(inventory):
    """Compare repository inputs and installed resources before starting Docker."""
    for group in ("code_files", "schema_files"):
        for item in inventory[group]:
            path = (ROOT / item["path"]).resolve()
            if not path.is_relative_to(ROOT) or digest(path) != item["sha256"]:
                raise ValueError("Inventory hash mismatch: " + item["path"])
    installed = []
    packages = {}
    for source in sorted((ROOT / "src").rglob("*")):
        if source.suffix not in {".py", ".sql", ".json"}:
            continue
        relative = source.relative_to(ROOT / "src")
        name = relative.parts[0]
        if name not in packages:
            module = importlib.import_module(name)
            path = Path(module.__file__).resolve().parent
            if not path.is_relative_to(Path(sys.prefix).resolve()) or path.is_relative_to(ROOT):
                raise ValueError("Install B's wheel in a separate venv and unset PYTHONPATH")
            packages[name] = path
        target = packages[name].joinpath(*relative.parts[1:])
        if not target.is_file() or digest(target) != digest(source):
            raise ValueError("Rebuild and install the wheel: " + str(relative))
        installed.append({**record(source), "installed_path": str(target)})
    return installed


def main(*, inventory_path="config/ac-inventory.json", additional_tests=(), tests=TESTS,
         scope="Installed NSW component chain and D02; no full inventory freeze or publication",
         pg_tmpfs=True):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12")
    inventory = json.loads((ROOT / inventory_path).read_text(encoding="utf-8"))
    installed = check_install(inventory)
    migrations = sorted((ROOT / "sql/migrations").glob("*.sql"))
    if [p.name[:3] for p in migrations] != [f"{i:03}" for i in range(1, 12)]:
        parser.error("Expected A migrations 001 through 011")
    if not {str(p.relative_to(ROOT)) for p in migrations} <= {
        item["path"] for item in inventory["schema_files"]
    }:
        parser.error("The inventory must include all eleven migrations")
    selected = [ROOT / "tests" / name for name in dict.fromkeys((*tests, *additional_tests))]
    for path in selected:
        if not path.is_file():
            parser.error("Missing test: " + str(path))
    audit_path = ROOT / "sql/tests/a03_database_roles.sql"
    dependencies = sorted(set((ROOT / "tests").glob("*.py")) | {
        p for p in (ROOT / "tests/fixtures").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    } | set(ROOT.glob("requirements*.txt")) | set((ROOT / "config").glob("*.json")) | {
        ROOT / "pyproject.toml", Path(__file__).resolve(), audit_path,
    } | set((ROOT / "tools").glob("verify_*postgres.py")))
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    write(out, "inputs.json", {
        "integration_head": run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).stdout.strip(),
        "working_tree": run(["git", "-C", str(ROOT), "status", "--short"]).stdout.splitlines(),
        "inventory": inventory, "migrations": [record(p) for p in migrations],
        "installed_files": installed, "tests": [record(p) for p in selected],
        "test_dependencies": [record(p) for p in dependencies],
        "python": sys.version, "image": IMAGE,
        "packages": {name: importlib.metadata.version(name) for name in (
            "arsia-native-intake", "openpyxl", "psycopg", "psycopg-binary", "pytest",
        )},
        "scope": scope, "postgres_storage": "tmpfs" if pg_tmpfs else "disposable container layer",
    })
    name = "arsia-b-ac-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(30)
    started = False
    try:
        with tempfile.TemporaryDirectory(prefix="arsia-b-ac-") as temp:
            envfile = Path(temp) / "postgres.env"
            envfile.write_text(
                f"POSTGRES_USER=arsia_owner\nPOSTGRES_DB=arsia\nPOSTGRES_PASSWORD={password}\n",
                encoding="utf-8",
            )
            envfile.chmod(0o600)
            storage = ["--tmpfs", "/var/lib/postgresql/data"] if pg_tmpfs else [
                "-e", "PGDATA=/var/lib/postgresql/official-review"]
            run([args.docker, "run", "-d", "--name", name, "--label", "arsia.scope=b-ac-integration",
                 "--env-file", str(envfile), "-p", "127.0.0.1::5432", *storage,
                 IMAGE, "postgres", "-c", "timezone=UTC", "-c", "log_timezone=UTC"])
            started = True
        for _ in range(150):
            ready = subprocess.run([args.docker, "exec", name, "pg_isready", "-h", "127.0.0.1",
                                    "-U", "arsia_owner", "-d", "arsia"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("PostgreSQL did not start")

        def sql(statement):
            result = run([args.docker, "exec", "-i", name, "psql", "-X", "-v", "ON_ERROR_STOP=1",
                          "-U", "arsia_owner", "-d", "arsia"], input=statement)
            return result.stdout + result.stderr

        with (out / "migrations.log").open("w", encoding="utf-8") as log:
            for migration in migrations:
                log.write(migration.name + "\n" + sql(migration.read_text(encoding="utf-8")))
        sql(f"ALTER ROLE arsia_loader PASSWORD '{password}';")
        test_run = secrets.token_hex(16)
        sql(f"ALTER DATABASE arsia SET arsia.test_run = '{test_run}';")
        audit = audit_path.read_text(encoding="utf-8")
        (out / "a03-before.log").write_text(sql(audit), encoding="utf-8")
        port = run([args.docker, "port", name, "5432"]).stdout.strip().rsplit(":", 1)[1]
        admin = f"postgresql://arsia_owner:{password}@127.0.0.1:{port}/arsia"
        loader = f"postgresql://arsia_loader:{password}@127.0.0.1:{port}/arsia"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(ARSIA_TEST_DSN=loader, ARSIA_TEST_ADMIN_DSN=admin,
                   D02_LOADER_DSN=loader, D02_ADMIN_DSN=admin, D02_REQUIRE_INSTALLED="1",
                   D02_EVIDENCE_DIR=str(out / "d02-evidence"), AC_REQUIRE_INSTALLED="1",
                   AC_EVIDENCE_DIR=str(out / "ac-evidence"), AC_TEST_RUN=test_run,
                   CD_EVIDENCE_DIR=str(out / "cd-evidence"), CD_REQUIRE_INSTALLED="1",
                   C07_TEST_DSN=loader)
        import psycopg
        with psycopg.connect(loader) as connection:
            row = connection.execute("""SELECT version(),current_user,session_user,
                current_setting('server_encoding'),current_setting('TimeZone'),
                datcollate,datctype,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls
                FROM pg_database,pg_roles WHERE datname=current_database() AND rolname=current_user""").fetchone()
            assert connection.info.server_version // 10000 == 16
            assert row[1:5] == ("arsia_loader", "arsia_loader", "UTF8", "UTC")
            assert row[7:] == (False, False, False, False)
            write(out, "environment.json", {"postgresql": row, "image": IMAGE})
        command = [sys.executable, "-m", "pytest", "-q", "-o", "pythonpath=",
                   *(str(p) for p in selected), "--junitxml=" + str(out / "pytest.xml")]
        write(out, "command.json", {"argv": command, "cwd": str(out), "pythonpath_removed": True})
        result = subprocess.run(command, env=env, cwd=out, text=True, capture_output=True)
        output = (result.stdout + result.stderr).replace(password, "[redacted]")
        report = out / "pytest.xml"
        if report.exists():
            report.write_text(report.read_text(encoding="utf-8").replace(password, "[redacted]"), encoding="utf-8")
        (out / "pytest.log").write_text(output, encoding="utf-8")
        print(output)
        (out / "a03-after.log").write_text(sql(audit), encoding="utf-8")
        with psycopg.connect(admin) as connection:
            counts = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in TABLES}
        write(out, "final-state.json", {"rows": counts, "all_zero": not any(counts.values())})
        suites = ET.parse(out / "pytest.xml").getroot().findall("testsuite")
        totals = {key: sum(int(s.attrib.get(key, "0")) for s in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        exit_code = result.returncode or (1 if any(counts.values()) or totals["skipped"] else 0)
        write(out, "summary.json", {
            **totals, "pytest_exit_code": result.returncode, "exit_code": exit_code,
            "permissions": "Original A03 audit passed before and after",
            "final_tables_empty": not any(counts.values()), "publication_performed": False,
            "boundary": scope,
        })
        return exit_code
    finally:
        if started:
            run([args.docker, "rm", "-f", "-v", name])
            write(out, "cleanup.json", {"container_removed": name, "persistent_volume_created": False,
                                       "anonymous_image_volumes_removed": True})


if __name__ == "__main__":
    raise SystemExit(main())
