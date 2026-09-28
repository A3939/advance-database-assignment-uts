#!/usr/bin/env python3
"""Verify D09 against real B10/E06 publications in disposable PostgreSQL 16."""

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
        tests=(
            "test_d09.py",
            "test_d09_full_build_postgres.py",
        ),
        scope=(
            "D09 real B10/E06 fixed-release dashboard acceptance: two successful "
            "S0 publications, one pinned page read, refresh-only pointer switch"
        ),
    )
    summary_path = args.output.resolve() / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(
        publication_performed=None if result else True,
        publication_scope="Private synthetic test database; no public release",
        d09_real_publication_acceptance=result == 0,
        pointer_switch_verified=result == 0,
        final_platform_accepted=False,
    )
    summary_path.write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    raise SystemExit(result)
