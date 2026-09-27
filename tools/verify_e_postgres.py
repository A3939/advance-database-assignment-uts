#!/usr/bin/env python3
"""Install E's fixes over pinned B components and test in private PostgreSQL 16."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

B_COMMIT = "1ae5ddbde746f3190fec5d58daaf948b0c483817"
ROOT = Path(__file__).resolve().parents[1]
FILES = ("sql/e/fp1.sql", "src/arsia_ingest/publication.py",
         "src/arsia_ingest/publication_checks.py", "tests/test_e_publication.py",
         "tests/test_e_gate_contract.py", "tests/test_e_postgres.py", "tools/verify_e_postgres.py",
         "config/e-independent-expectations.json", "docs/e/e02-interface-register.md")


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    out = args.output.resolve()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12")
    if args.database:
        from verify_d04_lineage_postgres import check_schema
        from verify_ac_postgres import main as verify
        check_schema()
        sys.argv[1:] = ["--output", str(out)]
        code = verify(inventory_path="config/cd-inventory.json",
                      tests=("test_e_publication.py", "test_e_gate_contract.py", "test_e_postgres.py"),
                      scope="E03/E06 installed acceptance over pinned B QA01-07; partial inventory; private S0 test releases only")
        receipt = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        receipt.pop("publication_performed", None)
        receipt.update(official_publication=False, isolated_test_pointer_updates=True,
                       boundary="E03/E06 and real S0 producers; not final inventory freeze, run_build acceptance or official replay")
        (out / "summary.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        return code
    out.mkdir(parents=True, exist_ok=False)
    assembly = out / "integration"
    run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(assembly), B_COMMIT])
    inputs = {
        "b_commit": B_COMMIT,
        "e_base": run(["git", "-C", str(ROOT), "rev-parse", "HEAD"]).stdout.strip(),
        "e_working_tree": run(["git", "-C", str(ROOT), "status", "--short"]).stdout.splitlines(),
        "overlay": [{"path": p, "sha256": digest(ROOT / p)} for p in FILES],
        "scope": "Detached verification assembly; no changes to B or E's working branch",
    }
    for relative in FILES:
        target = assembly / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    inventory_path = assembly / "config/cd-inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    e_paths = FILES[:3]
    inventory["components"].update(fp1=[e_paths[0]], publish=list(e_paths[1:]))
    inventory["code_files"].extend({"path": p, "sha256": digest(assembly / p)} for p in e_paths)
    inventory["code_files"].sort(key=lambda r: r["path"])
    inventory["scope"] += "; E03/E06 test overlay"
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    venv = out / "venv"
    run([sys.executable, "-m", "venv", str(venv)], env=env)
    python = str(venv / "bin/python")
    commands = [
        [python, "-m", "pip", "install", "-r", str(assembly / "requirements-db.txt")],
        [python, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(out / "wheel"), str(assembly)],
    ]
    with (out / "install.log").open("w", encoding="utf-8") as log:
        for command in commands:
            result = run(command, cwd=out, env=env)
            log.write(result.stdout + result.stderr)
        wheels = list((out / "wheel").glob("*.whl"))
        assert len(wheels) == 1
        command = [python, "-m", "pip", "install", "--no-deps", str(wheels[0])]
        commands.append(command)
        result = run(command, cwd=out, env=env)
        log.write(result.stdout + result.stderr)
    inputs.update(commands=commands, wheel={"path": str(wheels[0]), "sha256": digest(wheels[0])})
    (out / "assembly.json").write_text(json.dumps(inputs, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run([python, str(assembly / "tools/verify_e_postgres.py"),
                             "--database", "--output", str(out / "postgres")], cwd=out, env=env)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
