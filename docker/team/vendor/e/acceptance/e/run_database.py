"""Run E's acceptance checks with the pinned B database harness."""
import argparse
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from verify_ac_postgres import main
from verify_d04_lineage_postgres import check_schema


SYNTHETIC = (
    "test_e_acceptance_expectations.py",
    "test_s0.py",
    "test_at10_rule.py",
    "test_at10_rule_postgres.py",
    "test_d09_official_policy.py",
    "test_d09.py",
    "test_e07_postgres.py",
    "test_e08_postgres.py",
    "test_full_build_postgres.py",
    "test_s8_build_postgres.py",
    "test_d09_full_build_postgres.py",
    "test_d04_lineage_postgres.py",
    "test_d04_postgres.py",
    "test_e_integrated_postgres.py",
    "test_raw_load_postgres.py",
    "test_input_qa_postgres.py",
)


def verify():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("synthetic", "official"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    check_schema()
    if args.mode == "official":
        required = ("ARSIA_OFFICIAL_NATIVE_ROOT", "ARSIA_OFFICIAL_PREPARED_RUN")
        if any(not os.environ.get(key) for key in required):
            parser.error("Official replay needs the native files and complete prepared run")
    sys.argv[1:] = ["--output", str(args.output)]
    code = main(
        inventory_path="config/build-inventory.json",
        tests=SYNTHETIC if args.mode == "synthetic" else ("test_e09_official_postgres.py",),
        scope="E acceptance, executed by Role B: " + args.mode,
        pg_tmpfs=args.mode == "synthetic",
    )
    path = args.output / "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    groups = {}
    pure_modules = {"test_e_acceptance_expectations", "test_s0", "test_at10_rule",
                    "test_d09_official_policy", "test_d09"}
    selected = SYNTHETIC if args.mode == "synthetic" else ("test_e09_official_postgres.py",)
    for case in ET.parse(args.output / "pytest.xml").getroot().iter("testcase"):
        parts = case.attrib.get("classname", "").split(".")
        name = next((Path(path).stem for path in selected if Path(path).stem in parts), "unclassified")
        group = groups.setdefault(name, {"tests": 0, "scope": "no database" if name in pure_modules
                                        else "PostgreSQL module" if name != "unclassified" else "unclassified"})
        group["tests"] += 1
    summary.update(
        test_module_results=groups,
        test_count_scope="Total includes checks without a database and PostgreSQL modules; see test_module_results.",
        publication_performed=True if code == 0 else None,
        publication_scope="Disposable private test database only",
        execution_owner="Role B / Peixian assisting Role E",
        independent_member_signoff=False,
        final_platform_accepted=False,
    )
    path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(verify())
