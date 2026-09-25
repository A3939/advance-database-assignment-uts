#!/usr/bin/env python3
"""Check installed D05-D08 with B's real S0 chain and an isolated reader."""
import json
from verify_ac_postgres import ROOT, check_install, main
from verify_d04_lineage_postgres import A_COMMIT, check_schema


if __name__ == "__main__":
    check_schema()
    check_install(json.loads((ROOT / "config/analysis-inventory.json").read_text(encoding="utf-8")))
    raise SystemExit(main(
        inventory_path="config/cd-inventory.json",
        tests=("test_analysis_postgres.py", "test_analysis_inventory.py",
               "test_d05.py", "test_d06.py", "test_d07.py", "test_d08.py",
               "test_d05_postgres.py", "test_d06_postgres.py", "test_d07_postgres.py", "test_d08_postgres.py",
               "test_cd_inventory.py", "test_qa_joint_postgres.py"),
        scope=f"D05-D08 installed query integration; A {A_COMMIT}; real S0 chain and reader; "
              "seeded successful query fixtures; no E FP1/publication, official replay or full B10",
    ))
