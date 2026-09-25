#!/usr/bin/env python3
"""Reproduce PR18's lineage gap, or check the required fix, in private PG16."""
import argparse
import os
import subprocess
import sys

from verify_ac_postgres import ROOT, main

A_COMMIT = "c0824da06b6e7b3f73c4ddeab2114d10b7156913"


def check_schema():
    """Require the original A schema and permission audit, byte for byte."""
    def git(*args):
        return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                              capture_output=True).stdout

    expected = set(git("ls-tree", "--name-only", A_COMMIT,
                       "sql/migrations/").decode().splitlines())
    actual = {str(p.relative_to(ROOT)) for p in (ROOT / "sql/migrations").glob("*.sql")}
    if len(expected) != 11 or actual != expected:
        raise ValueError("Expected exactly A's eleven fixed migrations")
    for path in sorted(expected | {"sql/tests/a03_database_roles.sql"}):
        if (ROOT / path).read_bytes() != git("show", f"{A_COMMIT}:{path}"):
            raise ValueError("A schema or audit differs: " + path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--require-fix", action="store_true")
    args, remaining = parser.parse_known_args()
    sys.argv[1:] = remaining
    check_schema()
    os.environ["D04_REQUIRE_LINEAGE_FIX"] = "1" if args.require_fix else "0"
    mode = "fix acceptance" if args.require_fix else "defect reproduction"
    raise SystemExit(main(
        inventory_path="config/cd-inventory.json",
        tests=("test_d04_lineage_postgres.py", "test_cd_integration_postgres.py",
               "test_d04_postgres.py", "test_cd_inventory.py"),
        scope=f"D04 lineage {mode}; A {A_COMMIT}; partial inventory; no publication",
    ))
