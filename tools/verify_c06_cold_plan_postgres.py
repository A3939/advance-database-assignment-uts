#!/usr/bin/env python3
"""Check installed C06 file lookups and C10 integration in private PostgreSQL 16."""

from verify_ac_postgres import main
from verify_d04_lineage_postgres import check_schema


if __name__ == "__main__":
    check_schema()
    raise SystemExit(main(
        inventory_path="config/build-inventory.json",
        tests=("test_c06_cold_plan_postgres.py", "test_c10_integration_postgres.py",
               "test_c10_packaging.py", "test_qa_joint_postgres.py"),
        scope=("C06 file-selection plans, synthetic SQL equivalence and installed "
               "C10/QA01-07 regression; not full official acceptance"),
    ))
