#!/usr/bin/env python3
"""Check D08's first parent lookup and installed reader behavior in private PG16."""

from verify_ac_postgres import main
from verify_d04_lineage_postgres import check_schema


if __name__ == "__main__":
    check_schema()
    raise SystemExit(main(
        inventory_path="config/build-inventory.json",
        tests=("test_d08_cold_plan_postgres.py", "test_analysis_postgres.py",
               "test_d08_postgres.py", "test_d08.py"),
        scope=("D08 cold parent plans and installed reader/filter/permission regression; "
               "synthetic query fixtures, not official publication acceptance"),
    ))
