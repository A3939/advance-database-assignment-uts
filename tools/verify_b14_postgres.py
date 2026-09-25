#!/usr/bin/env python3
"""Run B14 against the installed wheel and a disposable PostgreSQL 16 instance."""
import argparse
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

from verify_ac_postgres import IMAGE, ROOT, TABLES, check_install, record, run, write


TESTS = ("test_recovery_postgres.py", "test_recovery.py", "test_runner.py",
         "test_runner_postgres.py", "test_b10_lifecycle_postgres.py")
A_VERSION = "c0824da06b6e7b3f73c4ddeab2114d10b7156913"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12")
    inventory = json.loads((ROOT / "config/ac-inventory.json").read_text(encoding="utf-8"))
    installed = check_install(inventory)
    migrations = sorted((ROOT / "sql/migrations").glob("*.sql"))
    if [p.name[:3] for p in migrations] != [f"{i:03}" for i in range(1, 12)]:
        parser.error("Expected A migrations 001 through 011")
    selected = [ROOT / "tests" / name for name in TESTS]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    dependencies = sorted(set((ROOT / "tests").glob("*.py")) | {
        p for p in (ROOT / "tests/fixtures").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    } | set(ROOT.glob("requirements*.txt")) | set((ROOT / "config").glob("*.json")) | {
        ROOT / "pyproject.toml", Path(__file__).resolve(), ROOT / "tools/verify_ac_postgres.py",
        ROOT / "sql/tests/a03_database_roles.sql",
    })
    write(out, "inputs.json", {
        "head": run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).stdout.strip(),
        "working_tree": run(["git", "-C", str(ROOT), "status", "--short"]).stdout.splitlines(),
        "a_version": A_VERSION, "migrations": [record(p) for p in migrations],
        "installed_files": installed, "test_files": [record(p) for p in selected],
        "dependencies": [record(p) for p in dependencies], "python": sys.version,
        "packages": {name: importlib.metadata.version(name) for name in (
            "arsia-native-intake", "openpyxl", "psycopg", "psycopg-binary", "pytest")},
        "image": IMAGE,
        "boundary": "Recovery component tests with seeded states and fixture-inventory manifests; no E publication",
        "faults": "Driver exceptions before/after real commit, plus real backend termination; no network proxy",
    })
    name = "arsia-b14-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(30)
    started = False
    try:
        with tempfile.TemporaryDirectory(prefix="arsia-b14-") as temp:
            envfile = Path(temp) / "postgres.env"
            envfile.write_text(f"POSTGRES_USER=arsia_owner\nPOSTGRES_DB=arsia\n"
                               f"POSTGRES_PASSWORD={password}\n", encoding="utf-8")
            envfile.chmod(0o600)
            run([args.docker, "run", "-d", "--name", name, "--label", "arsia.scope=b14-recovery",
                 "--env-file", str(envfile), "-p", "127.0.0.1::5432", "--tmpfs",
                 "/var/lib/postgresql/data", IMAGE, "postgres", "-c", "timezone=UTC", "-c", "log_timezone=UTC"])
            started = True
        for _ in range(150):
            ready = subprocess.run([args.docker, "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "arsia_owner", "-d", "arsia"],
                                   capture_output=True)
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
            for path in migrations:
                log.write(path.name + "\n" + sql(path.read_text(encoding="utf-8")))
        marker = secrets.token_hex(16)
        sql(f"ALTER ROLE arsia_loader PASSWORD '{password}';")
        sql(f"ALTER DATABASE arsia SET arsia.test_run = '{marker}';")
        audit = (ROOT / "sql/tests/a03_database_roles.sql").read_text(encoding="utf-8")
        (out / "a03-before.log").write_text(sql(audit), encoding="utf-8")
        port = run([args.docker, "port", name, "5432"]).stdout.strip().rsplit(":", 1)[1]
        admin = f"postgresql://arsia_owner:{password}@127.0.0.1:{port}/arsia"
        loader = f"postgresql://arsia_loader:{password}@127.0.0.1:{port}/arsia"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(ARSIA_TEST_DSN=loader, ARSIA_TEST_ADMIN_DSN=admin, B14_TEST_RUN=marker, AC_TEST_RUN=marker)
        import psycopg
        with psycopg.connect(loader) as conn:
            environment = conn.execute("""SELECT version(),current_user,session_user,
                current_setting('server_encoding'),current_setting('TimeZone'),
                rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user""").fetchone()
            assert conn.info.server_version // 10000 == 16
            assert environment[1:5] == ("arsia_loader", "arsia_loader", "UTF8", "UTC")
            assert environment[5:] == (False, False, False, False)
            write(out, "environment.json", {"postgresql": environment, "image": IMAGE})
        command = [sys.executable, "-m", "pytest", "-q", "-o", "pythonpath=", "-p", "no:cacheprovider",
                   *(str(p) for p in selected), "--basetemp=" + str(out / "pytest-tmp"),
                   "--junitxml=" + str(out / "pytest.xml")]
        write(out, "command.json", {"argv": command, "cwd": str(out), "pythonpath_removed": True})
        result = subprocess.run(command, env=env, cwd=out, text=True, capture_output=True)
        output = (result.stdout + result.stderr).replace(password, "[redacted]")
        (out / "pytest.log").write_text(output, encoding="utf-8")
        report = out / "pytest.xml"
        if report.exists():
            report.write_text(report.read_text(encoding="utf-8").replace(password, "[redacted]"), encoding="utf-8")
        print(output)
        (out / "a03-after.log").write_text(sql(audit), encoding="utf-8")
        with psycopg.connect(admin) as conn:
            counts = {table: conn.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in TABLES}
            locks = conn.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                                 "AND database=(SELECT oid FROM pg_database WHERE datname='arsia')").fetchone()[0]
        write(out, "final-state.json", {"rows": counts, "advisory_locks": locks})
        suites = ET.parse(report).getroot().findall("testsuite")
        totals = {key: sum(int(s.attrib.get(key, "0")) for s in suites)
                  for key in ("tests", "failures", "errors", "skipped")}
        groups = {}
        for suite in suites:
            for case in suite.findall("testcase"):
                group = case.attrib["classname"].split(".")[-1]
                groups[group] = groups.get(group, 0) + 1
        exit_code = result.returncode or int(any(counts.values()) or bool(locks) or bool(totals["skipped"]))
        write(out, "summary.json", {
            **totals, "test_groups": groups, "pytest_exit_code": result.returncode, "exit_code": exit_code,
            "a03_audit_before_and_after": True, "final_tables_empty": not any(counts.values()),
            "remaining_advisory_locks": locks, "publication_performed": False,
        })
        return exit_code
    finally:
        if started:
            run([args.docker, "rm", "-f", name])
            write(out, "cleanup.json", {"container_removed": name, "persistent_volume_created": False})


if __name__ == "__main__":
    raise SystemExit(main())
