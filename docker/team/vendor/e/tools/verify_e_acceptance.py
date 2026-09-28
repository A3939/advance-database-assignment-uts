#!/usr/bin/env python3
"""Replay E acceptance against a pinned, freshly installed B checkout."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VERSIONS = ROOT / "config/e-acceptance-versions.json"
FILES = {
    "acceptance/e/run_database.py": "tools/verify_e_platform_database.py",
    "acceptance/e/expected.py": "tests/e_acceptance_expected.py",
    "acceptance/e/test_expectations.py": "tests/test_e_acceptance_expectations.py",
    "acceptance/e/test_e07_postgres.py": "tests/test_e07_postgres.py",
    "acceptance/e/test_e08_postgres.py": "tests/test_e08_postgres.py",
    "acceptance/e/test_e09_official_postgres.py": "tests/test_e09_official_postgres.py",
    "acceptance/e/official_expected.py": "tests/e_official_expected.py",
    "config/e-acceptance-s0-v1.json": "config/e-acceptance-s0-v1.json",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args], text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("synthetic", "official"), default="synthetic")
    parser.add_argument("--native-root", type=Path)
    parser.add_argument("--prepared-run", type=Path)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("Use Python 3.12")
    if args.mode == "official" and (not args.native_root or not args.prepared_run):
        parser.error("Official mode needs --native-root and --prepared-run")
    out = args.output.resolve()
    if out.exists():
        parser.error("Use a new output directory")
    versions = read(VERSIONS)
    out.mkdir(parents=True)
    receipt = {
        "status": "failed", "mode": args.mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "versions": versions, "e_commit": git("rev-parse", "HEAD"),
        "e_working_tree": git("status", "--short").splitlines(),
        "verifier_sha256": digest(Path(__file__)), "commands": [],
        "execution_owner": versions["execution_owner"],
        "independent_member_signoff": False, "final_platform_accepted": False,
    }
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("ARSIA_", "AC_TEST_", "PG", "PYTHON", "PIP_"))
           and key not in {"VIRTUAL_ENV", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"}}
    env.update(GIT_LFS_SKIP_SMUDGE="1", PYTHONDONTWRITEBYTECODE="1",
               PIP_DISABLE_PIP_VERSION_CHECK="1")
    if args.mode == "official":
        env.update(ARSIA_OFFICIAL_NATIVE_ROOT=str(args.native_root.resolve()),
                   ARSIA_OFFICIAL_PREPARED_RUN=str(args.prepared_run.resolve()))

    def execute(*command):
        command = [str(part) for part in command]
        number = len(receipt["commands"]) + 1
        log = out / f"{number:02d}.log"
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(command, cwd=out, env=env, text=True,
                                    stdout=stream, stderr=subprocess.STDOUT)
        receipt["commands"].append({"argv": command, "exit_code": result.returncode,
                                    "log": log.name})
        if result.returncode:
            raise RuntimeError(f"Command {number} failed; see {log.name}")

    def checkout_pinned(destination, commit):
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("Use a full pinned commit ID")
        execute("git", "clone", "--no-hardlinks", "--no-checkout", ROOT, destination)
        present = subprocess.run(["git", "-C", str(destination), "cat-file", "-e", commit + "^{commit}"],
                                 cwd=out, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if present.returncode:
            # A fresh single-branch clone may not contain the other role's commit.
            execute("git", "-C", destination, "fetch", "--no-tags", git("remote", "get-url", "origin"), commit)
        execute("git", "-C", destination, "checkout", "--detach", commit)
        actual = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"],
                                         cwd=out, env=env, text=True).strip()
        if actual != commit:
            raise ValueError("Wrong pinned checkout")

    try:
        runtime = out / "runtime"
        checkout_pinned(runtime, versions["runtime_commit"])
        receipt["acceptance_files"] = []
        for source, destination in FILES.items():
            if args.mode == "synthetic" and source.endswith(("test_e09_official_postgres.py", "official_expected.py")):
                continue
            if args.mode == "official" and source not in {
                "acceptance/e/run_database.py", "acceptance/e/test_e09_official_postgres.py",
                "acceptance/e/official_expected.py",
            }:
                continue
            target = runtime / destination
            if target.exists():
                raise ValueError("Refusing to replace a runtime file: " + destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / source, target)
            receipt["acceptance_files"].append({
                "path": source, "runtime_path": destination, "sha256": digest(target),
            })
        python = out / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        execute(sys.executable, "-m", "venv", out / "venv")
        execute(python, "-m", "pip", "install", "-r", runtime / "requirements-db.txt")
        execute(python, "-m", "pip", "wheel", "--no-build-isolation", "--no-deps",
                "--wheel-dir", out / "wheel", runtime)
        wheels = list((out / "wheel").glob("*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected one project wheel")
        execute(python, "-m", "pip", "install", "--no-deps", wheels[0])
        execute(python, "-m", "pip", "check")
        receipt["wheel"] = {"filename": wheels[0].name, "sha256": digest(wheels[0])}
        execute(python, "-c", """
import hashlib, json, sys
from importlib.resources import files
from pathlib import Path
import arsia_d09
runtime, output = map(Path, sys.argv[1:])
installed = Path(arsia_d09.__file__).resolve()
assert installed.is_relative_to(Path(sys.prefix).resolve()), 'D09 was imported outside the clean environment'
rows = []
for relative in ('templates/dashboard.html', 'static/dashboard.css'):
    packaged = files('arsia_d09').joinpath(relative).read_bytes()
    source = (runtime / 'src/arsia_d09' / relative).read_bytes()
    assert packaged == source, 'Installed D09 asset differs: ' + relative
    rows.append({'path': relative, 'sha256': hashlib.sha256(packaged).hexdigest(),
                 'bytes': len(packaged), 'matches_pinned_source': True})
output.write_text(json.dumps({'installed_module': str(installed), 'assets': rows}, indent=2) + '\\n', encoding='utf-8')
""", runtime, out / "installed-d09-assets.json")
        receipt["installed_d09_assets"] = read(out / "installed-d09-assets.json")
        if args.mode == "synthetic":
            a_runtime = out / "a-environment"
            checkout_pinned(a_runtime, versions["a_environment_commit"])
            execute(python, a_runtime / "tools/verify_a09_cold_start.py",
                    "--output", out / "cold-start.json")
            cold = read(out / "cold-start.json")
            if cold["status"] != "passed" or not cold["cleanup"]["container_removed"]:
                raise ValueError("Cold start or cleanup failed")
            receipt["cold_start"] = {"status": cold["status"], "sha256": digest(out / "cold-start.json")}
        execute(python, runtime / "tools/verify_e_platform_database.py",
                "--mode", args.mode, "--output", out / "postgres")
        summary = read(out / "postgres/summary.json")
        cleanup = read(out / "postgres/cleanup.json")
        if summary["exit_code"] or summary["skipped"] or not summary["final_tables_empty"]:
            raise ValueError("Acceptance failed, skipped tests, or left rows behind")
        if not cleanup["container_removed"]:
            raise ValueError("Test container was not removed")
        receipt["database_summary"] = summary
        receipt["database_cleanup"] = cleanup
        if args.mode == "synthetic":
            execute(python, runtime / "tools/verify_b14_postgres.py", "--output", out / "recovery")
            recovery = read(out / "recovery/summary.json")
            recovery_cleanup = read(out / "recovery/cleanup.json")
            receipt["recovery_summary"] = recovery
            receipt["recovery_cleanup"] = recovery_cleanup
            if recovery["exit_code"] or recovery["skipped"] or not recovery["final_tables_empty"]:
                raise ValueError("Recovery regression failed")
            if not recovery_cleanup["container_removed"]:
                raise ValueError("Recovery test container was not removed")
        receipt["status"] = "passed"
    except Exception as error:
        receipt["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "receipt": str(out / "receipt.json"),
                      "error": receipt.get("error")}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
