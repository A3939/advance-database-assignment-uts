#!/usr/bin/env python3
"""Run B14 against the installed wheel and a disposable PostgreSQL 16 instance."""
import argparse
import hashlib
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
         "test_runner_postgres.py", "test_b10_lifecycle_postgres.py",
         "test_b14_verifier.py")
A_VERSION = "c0824da06b6e7b3f73c4ddeab2114d10b7156913"
# Exact migration bytes from A_VERSION, independent of the editable inventory.
A_MIGRATIONS = {
    "001_meta_registry.sql": "b44608c4baee8ce1d4ac6c3912a1a7d671772a1b305a32976b10f7bf00fe1893",
    "002_raw_record.sql": "550c022b204380af2c0b2ffffc48295df3b562fd217f99a62f392d8db15eb059",
    "003_b08_loader_role.sql": "e84a2d122bcb8f5edd6ffeb9974ef48eac3910ae801d5a929286734978f9269d",
    "004_meta_batch.sql": "5c828f4071cab7ea097ee5b001aa6aca8fb567f04889a091a02842cf14fbb801",
    "005_raw_vault.sql": "36fedf6f1c6b128e8006ad2e76815c44099c5557de8140deb04e599d4c4f14f8",
    "006_canonical.sql": "c6b414f581d15183d89d98bebda71f373827a945d9e3eb2d9a60e699054e37dd",
    "007_warehouse.sql": "32add012cc1f2919e0aa07926fea86922999b02dd37bb070e4bb2b6247fc87ee",
    "008_qa.sql": "408c3775b218808fceb40a4119f8e5f20735664e1775671f5876d838b6219e29",
    "009_database_roles.sql": "cd1b8f3c4969111cab71777ea063dfe89e69dc29566dbd779c708e2f889d03d5",
    "010_business_key.sql": "de7a14a6df0c0336c7f40c2178159e0f53a4f702da44cde9a20c53a95443d922",
    "011_review_validation_fixes.sql": "fb4d03819dbb4a37366aa5b3cb59fe4e8bec0d76eae3fcfbc3783ebb13f51de6",
}


def pinned_migrations(root):
    paths = sorted((root / "sql/migrations").glob("*.sql"))
    if [path.name for path in paths] != sorted(A_MIGRATIONS):
        raise ValueError("Expected the exact 11 migration filenames from A " + A_VERSION)
    contents = {}
    for path in paths:
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != A_MIGRATIONS[path.name]:
            raise ValueError("Migration differs from A " + A_VERSION + ": " + path.name)
        contents[path] = content
    return contents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12")
    try:
        migrations = pinned_migrations(ROOT)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    inventory = json.loads((ROOT / "config/ac-inventory.json").read_text(encoding="utf-8"))
    installed = check_install(inventory)
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
        "a_version": A_VERSION, "migrations": [
            {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(content).hexdigest()}
            for path, content in migrations.items()
        ],
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
            for path, content in migrations.items():
                log.write(path.name + "\n" + sql(content.decode("utf-8")))
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
