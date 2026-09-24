#!/usr/bin/env python3
"""Reproduce D02 integration in a disposable PostgreSQL 16 container.

This provisions its own cluster and never accepts a caller database DSN.
It requires separate, complete A and B Git checkouts at the recorded commits.
"""
from __future__ import annotations

import argparse
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
import xml.etree.ElementTree as ET

A_COMMIT = "c0824da06b6e7b3f73c4ddeab2114d10b7156913"
A_BASE = "d30405eab42ffb2475dea9f7322e7b803b879963"
B_COMMIT = "bc4ed6b000a354babe3cab65e5b5028a41ae304a"
D_BASE = "5d871e58100348b8cfb7dd11e3978bb233652efc"
IMAGE = "postgres@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67"


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root, *args):
    return run(["git", "-C", str(root), *args]).stdout.strip()


def write(root, name, value):
    (root / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a-root", type=Path, required=True)
    parser.add_argument("--b-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory")
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    parser.add_argument("--image", default=IMAGE)
    args = parser.parse_args()
    a, b, d = args.a_root.resolve(), args.b_root.resolve(), Path(__file__).resolve().parents[1]
    out = args.output.resolve()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12, as required by D02")
    for root, expected in ((a, A_COMMIT), (b, B_COMMIT)):
        if git(root, "rev-parse", "HEAD") != expected:
            parser.error(f"{root}: expected checkout {expected}")
        if git(root, "diff", "--name-only", "HEAD"):
            parser.error(f"{root}: tracked inputs must be unchanged")
    git(a, "merge-base", "--is-ancestor", A_BASE, A_COMMIT)
    git(d, "merge-base", "--is-ancestor", D_BASE, "HEAD")
    migrations = sorted((a / "sql/migrations").glob("*.sql"))
    if [p.name[:3] for p in migrations] != [f"{i:03}" for i in range(1, 12)]:
        parser.error("Expected exactly migrations 001 through 011")
    out.mkdir(parents=True, exist_ok=False)
    write(out, "inputs.json", {
        "a_commit": A_COMMIT, "a_base": A_BASE, "b_commit": B_COMMIT,
        "d_base": D_BASE, "d_checkout_head": git(d, "rev-parse", "HEAD"),
        "d_tracked_diff": git(d, "diff", "--name-only", "HEAD"),
        "migrations": [{"path": str(p.relative_to(a)), "sha256": sha(p)} for p in migrations],
        "d_runtime_files": [{"path": "D02/" + str(p.relative_to(d)), "sha256": sha(p)}
                            for p in [d / "src/arsia_d02/__init__.py", d / "src/arsia_d02/dimensions.py", d / "pyproject.toml"]],
        "test_file_sha256": sha(d / "integration/test_postgres.py"),
        "harness_sha256": sha(Path(__file__)), "python": sys.version,
        "host_platform": platform.platform(), "requested_image": args.image,
        "scope": "synthetic D02-only integration; no FP1, D03, publication or full-platform acceptance",
    })
    name = "arsia-d02-review-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(30)
    started = False
    code = 1
    try:
        with tempfile.TemporaryDirectory(prefix="arsia-d02-secret-") as temporary:
            envfile = Path(temporary) / "postgres.env"
            envfile.write_text(f"POSTGRES_USER=arsia_owner\nPOSTGRES_DB=arsia\nPOSTGRES_PASSWORD={password}\n")
            envfile.chmod(0o600)
            run([args.docker, "run", "-d", "--name", name, "--label", "arsia.scope=d02-isolated-validation",
                 "--env-file", str(envfile), "-p", "127.0.0.1::5432",
                 "--tmpfs", "/var/lib/postgresql/data", args.image])
        started = True
        for _ in range(100):
            # The image first starts a socket-only temporary initialization
            # server. Wait for TCP so migrations run on the final server.
            ready = subprocess.run([args.docker, "exec", name, "pg_isready", "-h", "127.0.0.1",
                                    "-U", "arsia_owner", "-d", "arsia"], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise RuntimeError("Isolated PostgreSQL did not become ready")
        def sql(text):
            result = run([args.docker, "exec", "-i", name, "psql", "-X", "-v", "ON_ERROR_STOP=1",
                          "-U", "arsia_owner", "-d", "arsia"], input=text)
            return result.stdout + result.stderr
        with (out / "migrations.log").open("w", encoding="utf-8") as log:
            for migration in migrations:
                log.write(migration.name + "\n" + sql(migration.read_text(encoding="utf-8")))
        # Password setup only: no GRANT, ALTER role attributes, or permission relaxation.
        sql(f"ALTER ROLE arsia_loader PASSWORD '{password}';")
        (out / "a03-permissions-before.log").write_text(sql((a / "sql/tests/a03_database_roles.sql").read_text()), encoding="utf-8")
        port = run([args.docker, "port", name, "5432"]).stdout.strip().rsplit(":", 1)[1]
        image_id = run([args.docker, "inspect", "--format", "{{.Image}}", name]).stdout.strip()
        write(out, "container.json", {"name": name, "image_id": image_id, "host": "127.0.0.1",
                                      "port": int(port), "storage": "private tmpfs", "shared_database_used": False})
        env = os.environ.copy()
        env.update(ARSIA_A_ROOT=str(a), ARSIA_B_ROOT=str(b), D02_EVIDENCE_DIR=str(out / "evidence"),
                   PYTHONPATH=os.pathsep.join((str(d / "src"), str(b / "src"))),
                   D02_ADMIN_DSN=f"postgresql://arsia_owner:{password}@127.0.0.1:{port}/arsia",
                   D02_LOADER_DSN=f"postgresql://arsia_loader:{password}@127.0.0.1:{port}/arsia")
        result = subprocess.run([sys.executable, "-m", "pytest", "-q", str(d / "tests"), str(d / "integration"),
                                 "--junitxml=" + str(out / "pytest.xml")], env=env, text=True, capture_output=True)
        code = result.returncode
        (out / "pytest.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        print(result.stdout + result.stderr)
        (out / "a03-permissions-after.log").write_text(sql((a / "sql/tests/a03_database_roles.sql").read_text()), encoding="utf-8")
        (out / "final-database-state.log").write_text(sql("""SELECT 'dim_source' AS object,count(*) FROM dw.dim_source
            UNION ALL SELECT 'dim_month',count(*) FROM dw.dim_month
            UNION ALL SELECT 'dim_severity',count(*) FROM dw.dim_severity
            UNION ALL SELECT 'fact_crash',count(*) FROM dw.fact_crash
            UNION ALL SELECT 'batch',count(*) FROM meta.batch
            UNION ALL SELECT 'current_release',count(*) FROM meta.current_release;"""), encoding="utf-8")
        suite = ET.parse(out / "pytest.xml").getroot().find("testsuite")
        write(out, "summary.json", {**suite.attrib, "pytest_exit_code": code,
              "validation_layers": {
                  "fixed_s0_definitions": "executed",
                  "real_FrozenManifest_constructor_and_B10_objects": "executed with actual indexed bytes; interface-only",
                  "full_B09_freeze_and_B10_build": "blocked at preflight: incomplete platform inventory and bindings"},
              "a03_permissions_unchanged": True, "publication_performed": False})
    finally:
        if started:
            run([args.docker, "rm", "-f", name])
            write(out, "cleanup.json", {"isolated_container_removed": name, "persistent_volume_created": False})
    return code


if __name__ == "__main__":
    raise SystemExit(main())
