#!/usr/bin/env python3
"""Check installed C09 parent lookups in a fresh PostgreSQL 16 database."""

from verify_ac_postgres import main
from verify_d04_lineage_postgres import check_schema


if __name__ == "__main__":
    check_schema()
    raise SystemExit(main(
        inventory_path="config/build-inventory.json",
        tests=("test_c09_canonical.py", "test_c09_postgres.py",
               "test_c09_acceptance_postgres.py", "test_c09_cold_plan_postgres.py"),
        scope=("C09 installed-package regression, including a fresh "
               "1,001-crash/2,001-unit parent lookup; not full-build acceptance"),
    ))
