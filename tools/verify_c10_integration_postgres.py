#!/usr/bin/env python3
"""Check C10's installed B binding with A's fixed schema in private PG16."""
from verify_ac_postgres import main
from verify_d04_lineage_postgres import A_COMMIT, check_schema


if __name__ == "__main__":
    check_schema()
    raise SystemExit(main(
        inventory_path="config/cd-inventory.json",
        tests=("test_c10_year_coverage_postgres.py", "test_c10_integration_postgres.py", "test_cd_inventory.py",
               "test_cd_integration_postgres.py", "test_runner.py"),
        scope=f"Installed C10/B interface and CD regressions; A {A_COMMIT}; "
              "partial inventory; no combined QA01-07 or publication acceptance",
    ))
