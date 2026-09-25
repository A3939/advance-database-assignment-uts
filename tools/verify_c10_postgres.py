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
OVERLAY = (
    "config/c10-inventory.json",
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
    # Full originals need more temporary disk than Docker's default tmpfs.
    harness = checkout / "tools/verify_ac_postgres.py"
    text = harness.read_text()
    text = text.replace(
        '"--tmpfs",\n                 "/var/lib/postgresql/data"',
        '"--mount",\n                 "type=volume,destination=/var/lib/postgresql/data"',
    )
    text = text.replace(
        '[args.docker, "rm", "-f", name]', '[args.docker, "rm", "-f", "-v", name]'
    )
    text = text.replace(
        '"persistent_volume_created": False', '"anonymous_volume_removed": True'
    )
    harness.write_text(text)
    versions = []
    for path in OVERLAY:
        target = checkout / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
        versions.append(
            {"path": path, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        )
    (out / "assembly.json").write_text(
        json.dumps(
            {
                "b_commit": B_COMMIT,
                "a_commit": A_COMMIT,
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
            "pytest==8.4.2",
            "psycopg[binary]==3.3.6",
            "setuptools==80.9.0",
            "wheel==0.45.1",
        ]
    )
    entry = checkout / "tools/run_c10_checks.py"
    entry.write_text(
        "from verify_ac_postgres import main\nraise SystemExit(main(inventory_path='config/cd-inventory.json', tests=('test_c10_postgres.py','test_c10_year_coverage_postgres.py','test_c06_postgres.py'), scope='C10 installed B callback; no final platform freeze or publication'))\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    if args.raw_root:
        env["C10_RAW_ROOT"] = str(args.raw_root.resolve())
    run([python, entry, "--output", out / "postgres"], cwd=out, env=env)


if __name__ == "__main__":
    main()
