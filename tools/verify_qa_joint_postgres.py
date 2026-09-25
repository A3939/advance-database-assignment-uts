#!/usr/bin/env python3
"""Validate seven QA groups together without adding a test publication callback."""
from verify_ac_postgres import main
from verify_d04_lineage_postgres import A_COMMIT, check_schema


if __name__ == "__main__":
    check_schema()
    raise SystemExit(main(
        inventory_path="config/cd-inventory.json",
        tests=("test_qa_joint_postgres.py", "test_input_qa_postgres.py",
               "test_c10_integration_postgres.py", "test_c10_year_coverage_postgres.py",
               "test_d04_lineage_postgres.py", "test_cd_inventory.py",
               "test_cd_integration_postgres.py", "test_runner.py"),
        scope=f"S0 QA01-07 on one installed component chain; A {A_COMMIT}; "
              "partial inventory; no real FP1, E gate, official replay or publication",
    ))
