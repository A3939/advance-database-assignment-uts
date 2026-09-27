#!/usr/bin/env python3
"""Run the NSW SQL and installation regressions in their own PostgreSQL 16 database."""
from verify_ac_postgres import main
from verify_d04_lineage_postgres import check_schema


if __name__ == "__main__":
    check_schema()
    raise SystemExit(main(
        inventory_path="config/build-inventory.json",
        tests=("test_nsw_cold_plan_postgres.py", "test_c03_nsw_postgres.py",
               "test_c03_nsw_projection.py", "test_c03_packaging.py"),
        scope="NSW cold-plan, projection and installed SQL regression; no full build",
    ))
