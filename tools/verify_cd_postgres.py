#!/usr/bin/env python3
"""Verify the installed three-source B/C/D component chain in a private database."""
from verify_ac_postgres import main


if __name__ == "__main__":
    raise SystemExit(main(
        inventory_path="config/cd-inventory.json",
        additional_tests=(
            "test_cd_inventory.py", "test_project_dispatcher.py", "test_cd_integration_postgres.py",
            "test_c04_vic_projection.py", "test_c45_packaging.py", "test_c45_postgres.py",
            "test_c07_node_location.py", "test_c07_boundaries.py", "test_c07_packaging.py",
            "test_c07_postgres.py", "test_d03.py", "test_d03_postgres.py",
            "test_d04.py", "test_d04_postgres.py",
            "test_d04_lineage_postgres.py",
        ),
        scope="Installed three-source projection, A06, C09, D02/D03 and D04; no full B10 or publication",
    ))
