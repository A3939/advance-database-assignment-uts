#!/usr/bin/env python3
"""Test C's installed wheel with pinned A migrations in a private PostgreSQL 16."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
A_COMMIT = "c0824da06b6e7b3f73c4ddeab2114d10b7156913"
B_HARNESS = "d5239db471e33ce30c137e9087f712c14cc6cea0"
TESTS = (
    "test_c03_nsw_projection.py", "test_c03_nsw_postgres.py", "test_c03_packaging.py",
    "test_nsw_cold_plan_postgres.py", "test_person_checks.py", "test_c06_postgres.py",
    "test_restricted_person.py", "test_c06_replay_cli.py", "test_c06_cold_plan_postgres.py",
    "test_c09_canonical.py", "test_c09_postgres.py", "test_c09_acceptance_postgres.py",
    "test_c09_cold_plan_postgres.py", "test_c10_qa.py", "test_c10_packaging.py",
)


def run(args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def git_bytes(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def record(root, path):
    return {"path": str(path.relative_to(root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12 with requirements-c06.txt installed")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    checkout = out / "c-checkout"
    run(["git", "clone", "--shared", "--no-checkout", ROOT, checkout])
    run(["git", "-C", checkout, "checkout", "--detach", git_bytes("rev-parse", "HEAD").decode().strip()])
    # Include this checkout's edits; record their bytes before testing.
    paths = git_bytes("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    files = [Path(os.fsdecode(p)) for p in paths.split(b"\0") if p]
    for path in files:
        if (ROOT / path).is_file():
            (checkout / path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, checkout / path)
        elif (checkout / path).is_file():
            (checkout / path).unlink()
    dependencies = []
    migration_paths = git_bytes("ls-tree", "-r", "--name-only", A_COMMIT, "sql/migrations").decode().splitlines()
    for commit, path in [*((A_COMMIT, path) for path in migration_paths),
                         (A_COMMIT, "sql/tests/a03_database_roles.sql"),
                         (B_HARNESS, "tools/verify_ac_postgres.py")]:
        target = checkout / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git_bytes("show", commit + ":" + path))
        dependencies.append({"commit": commit, **record(checkout, target)})
    code = [record(checkout, p) for p in sorted((checkout / "src").rglob("*"))
            if p.suffix in {".py", ".sql", ".json"}]
    schema = [record(checkout, checkout / p) for p in migration_paths]
    inventory = {"scope": "Verification inputs only; not a B09 platform inventory",
                 "code_files": code, "schema_files": schema}
    (checkout / "config/c-performance-verification.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    (out / "assembly.json").write_text(json.dumps({
        "c_head": git_bytes("rev-parse", "HEAD").decode().strip(),
        "c_changes": git_bytes("status", "--short").decode().splitlines(),
        "scope": "C wheel; A schema and B test harness only, no B runtime overlay",
        "dependencies": dependencies, "code_files": code,
    }, indent=2) + "\n", encoding="utf-8")
    run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
         "--no-index", checkout, "-w", out / "wheels"])
    run([sys.executable, "-m", "venv", out / "venv"])
    python = out / "venv/bin/python"
    wheel, = (out / "wheels").glob("*.whl")
    run([python, "-m", "pip", "install", wheel, "-r", ROOT / "requirements-c06.txt"])
    entry = checkout / "tools/run_c_performance.py"
    entry.write_text(
        "from verify_ac_postgres import main\nraise SystemExit(main("
        "inventory_path='config/c-performance-verification.json', "
        f"tests={TESTS!r}, scope='Installed C03/C06/C09 regressions; "
        "synthetic inputs, no official replay or publication'))\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("ARSIA_REPOSITORY", None)
    run([python, entry, "--output", out / "postgres"], cwd=out, env=env)


if __name__ == "__main__":
    main()
