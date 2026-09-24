#!/usr/bin/env python3
"""Test the installed B/D02 package in a disposable PostgreSQL 16 container."""
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

A_COMMIT = "c0824da06b6e7b3f73c4ddeab2114d10b7156913"
B_BASE = "bc4ed6b000a354babe3cab65e5b5028a41ae304a"
IMAGE = "postgres@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67"
ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *args):
    return run(["git", "-C", str(root), *args]).stdout.strip()


def write(root, name, value):
    (root / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    args = parser.parse_args()
    a, out = args.a_root.resolve(), args.output.resolve()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12")
    if git(a, "rev-parse", "HEAD") != A_COMMIT or git(a, "diff", "--name-only", "HEAD"):
        parser.error("Use an unchanged A checkout at " + A_COMMIT)
    git(ROOT, "merge-base", "--is-ancestor", B_BASE, "HEAD")
    import arsia_d02.dimensions as installed
    installed_path = Path(installed.__file__).resolve()
    if not installed_path.is_relative_to(Path(sys.prefix).resolve()) or installed_path.is_relative_to(ROOT):
        parser.error("Install B's wheel in a separate venv and unset PYTHONPATH")
    if digest(installed_path) != digest(ROOT / "src/arsia_d02/dimensions.py"):
        parser.error("Rebuild and install the wheel after changing D02")
    migrations = sorted((a / "sql/migrations").glob("*.sql"))
    if [p.name[:3] for p in migrations] != [f"{i:03}" for i in range(1, 12)]:
        parser.error("Expected exactly A migrations 001 through 011")
    out.mkdir(parents=True, exist_ok=False)
    write(out, "inputs.json", {
        "a_commit": A_COMMIT, "b_base": B_BASE, "integration_head": git(ROOT, "rev-parse", "HEAD"),
        "tracked_changes": git(ROOT, "diff", "--name-only", "HEAD").splitlines(),
        "inventory": json.loads((ROOT / "config/d02-inventory.json").read_text()),
        "migrations": [{"path": str(p.relative_to(a)), "sha256": digest(p)} for p in migrations],
        "installed_module": str(installed_path), "installed_sha256": digest(installed_path),
        "python": sys.version, "image": IMAGE,
        "tests": [{"path": p, "sha256": digest(ROOT / p)} for p in
                  ("tests/test_d02.py", "tests/test_d02_postgres.py", "tests/d02_support.py")],
        "scope": "D02-only; partial manifest interface; no full platform build or publication",
    })
    name = "arsia-b-d02-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(30)
    started = False
    try:
        with tempfile.TemporaryDirectory(prefix="arsia-b-d02-") as temp:
            envfile = Path(temp) / "postgres.env"
            envfile.write_text(f"POSTGRES_USER=arsia_owner\nPOSTGRES_DB=arsia\nPOSTGRES_PASSWORD={password}\n")
            envfile.chmod(0o600)
            run([args.docker, "run", "-d", "--name", name, "--label", "arsia.scope=b-d02-integration",
                 "--env-file", str(envfile), "-p", "127.0.0.1::5432", "--tmpfs", "/var/lib/postgresql/data", IMAGE])
        started = True
        for _ in range(100):
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
        audit = (a / "sql/tests/a03_database_roles.sql").read_text(encoding="utf-8")
        (out / "a03-before.log").write_text(sql(audit), encoding="utf-8")
        port = run([args.docker, "port", name, "5432"]).stdout.strip().rsplit(":", 1)[1]
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(D02_EVIDENCE_DIR=str(out / "evidence"), D02_REQUIRE_INSTALLED="1",
                   D02_ADMIN_DSN=f"postgresql://arsia_owner:{password}@127.0.0.1:{port}/arsia",
                   D02_LOADER_DSN=f"postgresql://arsia_loader:{password}@127.0.0.1:{port}/arsia")
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-o", "pythonpath=",
                                 str(ROOT / "tests/test_d02.py"), str(ROOT / "tests/test_d02_postgres.py"),
                                 "--junitxml=" + str(out / "pytest.xml")], env=env, cwd=out,
                                 text=True, capture_output=True)
        (out / "pytest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        print(result.stdout + result.stderr)
        (out / "a03-after.log").write_text(sql(audit), encoding="utf-8")
        (out / "final-state.log").write_text(sql("""SELECT 'dim_source' AS object,count(*) FROM dw.dim_source
            UNION ALL SELECT 'dim_month',count(*) FROM dw.dim_month
            UNION ALL SELECT 'dim_severity',count(*) FROM dw.dim_severity
            UNION ALL SELECT 'fact_crash',count(*) FROM dw.fact_crash
            UNION ALL SELECT 'batch',count(*) FROM meta.batch
            UNION ALL SELECT 'current_release',count(*) FROM meta.current_release;"""), encoding="utf-8")
        suite = ET.parse(out / "pytest.xml").getroot().find("testsuite")
        write(out, "summary.json", {**suite.attrib, "exit_code": result.returncode,
              "permissions": "Original A03 audit passed before and after",
              "full_build": "Blocked at real B10 preflight by incomplete inventory",
              "publication_performed": False})
        return result.returncode
    finally:
        if started:
            run([args.docker, "rm", "-f", name])
            write(out, "cleanup.json", {"container_removed": name, "persistent_volume_created": False})


if __name__ == "__main__":
    raise SystemExit(main())
