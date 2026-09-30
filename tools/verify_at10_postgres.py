#!/usr/bin/env python3
"""Check AT10 rule changes from an installed wheel in a private PG16 database."""
import argparse
import json
from pathlib import Path

from verify_ac_postgres import main


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--output", type=Path, required=True)
    args, _ = parser.parse_known_args()
    result = main(
        inventory_path="config/build-inventory.json",
        tests=("test_at10_rule.py", "test_at10_rule_postgres.py", "test_c03_nsw_postgres.py",
               "test_c10_integration_postgres.py", "test_official_definitions.py"),
        scope="AT10 synthetic rule rebuild, independent C10 rejection, and unchanged NSW defaults",
    )
    path = args.output.resolve() / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary.update(publication_performed=True if result == 0 else None,
                   publication_scope="Private synthetic test publications; no official release",
                   final_platform_accepted=False)
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(result)
