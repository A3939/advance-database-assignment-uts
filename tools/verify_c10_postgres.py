#!/usr/bin/env python3
"""Build C10 with the pinned B component checkout, then test its installed wheel."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
B_COMMIT = "2750d8ea3f909cfacdc4cb10b35b87ffe729a468"
A_COMMIT = "c0824da06b6e7b3f73c4ddeab2114d10b7156913"
B_HARNESS = "d5239db471e33ce30c137e9087f712c14cc6cea0"
OVERLAY = (
    "config/c10-inventory.json",
    "src/arsia_c/projections/nsw.py",
    "src/arsia_c/canonical_validation.py",
    *(
        "src/arsia_c/projections/sql/" + path.name
        for path in sorted((ROOT / "src/arsia_c/projections/sql").glob("*.sql"))
    ),
    "src/arsia_c/qa.py",
    "src/arsia_c/qa_expectations.py",
    "src/arsia_c/person_checks.py",
    "src/arsia_c/restricted_person.py",
    "src/arsia_c/config/c06-syn-1.json",
    "src/arsia_c/config/c06-vic-r1.json",
    "src/arsia_c/config/vic-restricted-inputs-v1.json",
    "src/arsia_c/config/vic-restricted-use-v1.json",
    "src/arsia_c/sql/c06_vic_person_checks.sql",
    *(
        "src/arsia_c/sql/" + name
        for name in (
            "c10_qa03_expectation.sql",
            "c10_qa03_projected.sql",
            "c10_qa04_auxiliary.sql",
            "c10_qa05_semantics.sql",
            "c10_qa07_location.sql",
        )
    ),
    "tests/test_c10_postgres.py",
    "tests/test_c10_year_coverage_postgres.py",
    "tests/test_c06_postgres.py",
    "sql/qa/c06_vic_person_checks.sql",
)


def run(args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--raw-root", type=Path, help="Include complete adopted VIC and QLD originals"
    )
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    checkout = out / "components"
    run(["git", "clone", "--shared", "--no-checkout", ROOT, checkout])
    run(["git", "-C", checkout, "checkout", "--detach", B_COMMIT])
    for path in sorted((checkout / "sql/migrations").glob("*.sql")):
        expected = subprocess.check_output(
            ["git", "-C", str(ROOT), "show", A_COMMIT + ":sql/migrations/" + path.name]
        )
        if path.read_bytes() != expected:
            raise ValueError("A migration mismatch: " + path.name)
    harness = checkout / "tools/verify_ac_postgres.py"
    harness.write_bytes(subprocess.check_output(
        ["git", "-C", str(ROOT), "show", B_HARNESS + ":tools/verify_ac_postgres.py"]
    ))
    versions = []
    for path in OVERLAY:
        target = checkout / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
        versions.append(
            {"path": path, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        )
    # These hashes describe this partial test assembly, not a final B09 freeze.
    fragment_path = checkout / "config/cd-inventory.json"
    fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
    for item in fragment["code_files"]:
        item["sha256"] = hashlib.sha256((checkout / item["path"]).read_bytes()).hexdigest()
    fragment_path.write_text(json.dumps(fragment, indent=2) + "\n", encoding="utf-8")
    (out / "assembly.json").write_text(
        json.dumps(
            {
                "b_commit": B_COMMIT,
                "a_commit": A_COMMIT,
                "harness_commit": B_HARNESS,
                "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
                "overlay": versions,
                "scope": "C10 component interface test; partial inventory, no FP1 or publication",
            },
            indent=2,
        )
        + "\n"
    )
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            checkout,
            "-w",
            out / "wheels",
        ]
    )
    run([sys.executable, "-m", "venv", out / "venv"])
    python = out / "venv/bin/python"
    run(
        [
            python,
            "-m",
            "pip",
            "install",
            *list((out / "wheels").glob("*.whl")),
            "-r",
            ROOT / "requirements-c06.txt",
        ]
    )
    entry = checkout / "tools/run_c10_checks.py"
    entry.write_text(
        "from verify_ac_postgres import main\nraise SystemExit(main(inventory_path='config/cd-inventory.json', tests=('test_c10_postgres.py','test_c10_year_coverage_postgres.py','test_c06_postgres.py'), pg_tmpfs=False, scope='C10 installed B callback; no final platform freeze or publication'))\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    if args.raw_root:
        env["C10_RAW_ROOT"] = str(args.raw_root.resolve())
    run([python, entry, "--output", out / "postgres"], cwd=out, env=env)


if __name__ == "__main__":
    main()
