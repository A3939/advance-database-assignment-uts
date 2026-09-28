"""Run the unchanged E and B checks against the separate Compose test database."""
import ast
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from . import common


TABLES = {
    "meta.source", "meta.resource", "meta.batch", "meta.current_release", "raw.record",
    "rv.hub_crash", "rv.hub_unit", "rv.sat_crash", "rv.sat_unit", "rv.link_crash_unit",
    "canonical.crash", "canonical.unit", "dw.dim_source", "dw.dim_month",
    "dw.dim_severity", "dw.fact_crash", "qa.check_result",
}
EXTRA_TESTS = ("test_d09_postgres.py", "test_build_integration.py")
GUARD_TESTS = ("test_team_acceptance.py", "test_team_docker_common.py", "test_team_cli.py")


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selection(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    require(len(values) == 1, "Expected one literal test selection: " + name)
    names = ast.literal_eval(values[0])
    require(isinstance(names, (list, tuple)) and names and all(
        isinstance(item, str) and Path(item).name == item and item.startswith("test_") and item.endswith(".py")
        for item in names), "Invalid test selection: " + name)
    require(len(set(names)) == len(names), "Duplicate test module: " + name)
    return tuple(names)


def test_results(path, selected):
    groups = {}
    failures, skips = [], []
    tree = ET.parse(path).getroot()
    expected = {Path(name).stem for name in selected}
    for case in tree.iter("testcase"):
        classname = case.attrib.get("classname", "")
        name = case.attrib.get("name", "")
        require(classname and name, "JUnit test identity is missing")
        module = next((part for part in classname.split(".") if part in expected), None)
        require(module, "Unexpected JUnit module: " + classname)
        status = "error" if case.find("error") is not None else (
            "failure" if case.find("failure") is not None else
            "skipped" if case.find("skipped") is not None else "passed")
        record = groups.setdefault(module, {"tests": 0, "passed": 0, "failures": 0,
                                            "errors": 0, "skipped": 0, "test_names": []})
        record["tests"] += 1
        record[{"failure": "failures", "error": "errors"}.get(status, status)] += 1
        record["test_names"].append(name)
        if status in {"failure", "error"}:
            failures.append(classname + "::" + name)
        elif status == "skipped":
            skips.append(classname + "::" + name)
    require(set(groups) == expected, "JUnit is missing selected test modules")
    totals = {key: sum(group[key] for group in groups.values())
              for key in ("tests", "passed", "failures", "errors", "skipped")}
    require(totals["tests"] > 0, "No acceptance tests ran")
    for group in groups.values():
        group["test_names"].sort()
    return {**totals, "modules": dict(sorted(groups.items())),
            "failed_test_names": failures, "skipped_test_names": skips}


def target_guard():
    from psycopg.conninfo import conninfo_to_dict

    options = conninfo_to_dict(common.dsn("owner"))
    require(options.get("host") == "acceptance-db" and options.get("dbname") == "arsia",
            "Acceptance requires the separate acceptance-db service and arsia database")
    with common.connect("owner") as connection:
        row = connection.execute("SELECT current_database(), current_setting('arsia.team_environment',true), "
                                 "current_user, session_user").fetchone()
        require(row == ("arsia", "acceptance", "arsia_owner", "arsia_owner"),
                "The acceptance database identity or server marker is wrong")
        require(connection.info.server_version // 10000 == 16, "Acceptance requires PostgreSQL 16")
    return {"host": "acceptance-db", "database": row[0], "server_marker": row[1],
            "owner": row[2], "postgres_major": 16}


def empty_tables():
    counts = common.table_counts()
    require(set(counts) == TABLES and all(type(count) is int and count == 0 for count in counts.values()),
            "Acceptance requires all seventeen application tables to be empty")
    return counts


def copy_reference(target):
    """Tests need inventory source bytes, but imports still use the installed wheel."""
    target.mkdir()
    for directory in ("src", "tests", "tools", "config", "sql"):
        shutil.copytree(common.ROOT / directory, target / directory,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    shutil.copytree(common.ROOT / "docker/team", target / "docker/team",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"))
    for source in (*common.ROOT.glob("requirements*.txt"), common.ROOT / "pyproject.toml"):
        shutil.copyfile(source, target / source.name)
    inventory = json.loads((common.ROOT / "config/d09-inventory.json").read_text(encoding="utf-8"))
    relative = Path(inventory["acceptance"]["evidence"]) / "summary.json"
    source = (common.ROOT / relative).resolve()
    require(source.is_relative_to(common.ROOT.resolve()) and source.is_file(),
            "D09's recorded acceptance summary is missing")
    destination = target / source.relative_to(common.ROOT.resolve())
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return [{"path": str(path.relative_to(target)), "sha256": digest(path)}
            for path in sorted(target.rglob("*")) if path.is_file()]


def environment(output, marker):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("PYTHON", "ARSIA_TEST_", "AC_", "B14_", "D02_", "CD_", "C07_", "PG"))}
    env.update(PYTHONDONTWRITEBYTECODE="1", AC_TEST_RUN=marker, B14_TEST_RUN=marker,
               ARSIA_TEST_DSN=common.dsn("loader"), ARSIA_TEST_ADMIN_DSN=common.dsn("owner"),
               ARSIA_TEST_READER_DSN=common.dsn("reader"),
               D02_LOADER_DSN=common.dsn("loader"), D02_ADMIN_DSN=common.dsn("owner"),
               C07_TEST_DSN=common.dsn("loader"), AC_REQUIRE_INSTALLED="1",
               CD_REQUIRE_INSTALLED="1", D02_REQUIRE_INSTALLED="1")
    for key, name in (("AC_EVIDENCE_DIR", "ac-evidence"), ("CD_EVIDENCE_DIR", "cd-evidence"),
                      ("D02_EVIDENCE_DIR", "d02-evidence")):
        path = output / name
        path.mkdir()
        env[key] = str(path)
    return env


def pytest_command(reference, config, directory, tests):
    paths = [reference / "tests" / name for name in tests]
    require(all(path.is_file() for path in paths), "A selected acceptance test is missing")
    return [sys.executable, "-m", "pytest", "-q", "-c", str(config),
            "--rootdir=" + str(reference), "--import-mode=prepend", "-o", "pythonpath=",
            "-p", "no:cacheprovider", "--basetemp=" + str(directory / "pytest-tmp"),
            "--junitxml=" + str(directory / "pytest.xml"), *(str(path) for path in paths)]


def redactor():
    from psycopg.conninfo import conninfo_to_dict

    passwords = {conninfo_to_dict(common.dsn(role)).get("password") for role in ("owner", "loader", "reader")}
    def redact(value):
        for password in passwords - {None, ""}:
            value = value.replace(password, "[redacted]")
        return value
    return redact


def run(output: Path) -> dict:
    output = output.resolve()
    require(not output.exists(), "Use a new acceptance output directory")
    require(not output.is_relative_to(common.ROOT.resolve()), "Keep acceptance output outside the source directory")
    output.mkdir(parents=True)
    result = {"status": "failed", "exit_code": 1, "started_at": datetime.now(timezone.utc).isoformat(),
              "executor": os.environ.get("ARSIA_EXECUTOR"),
              "independent_member_signoff": False, "final_platform_accepted": False,
              "scope": "Installed wheel, unchanged synthetic E tests and B recovery/UI checks; private Compose database",
              "official_replay": "NOT_RUN", "runs": {}}
    checked_target = False
    redact = lambda value: value
    try:
        require(result["executor"] and result["executor"].strip() and
                not result["executor"].strip().startswith("REPLACE_"),
                "Set ARSIA_EXECUTOR to the actual person running these commands")
        result["database"] = target_guard()
        checked_target = True
        redact = redactor()
        result["initialization"] = common.initialize()
        result["installed_package"] = common.check_installation()
        image_inputs = common.ROOT.parent / "image-inputs.json"
        shutil.copyfile(image_inputs, output / "image-inputs.json")
        result["runtime"] = {
            "declared_revision": os.environ.get("ARSIA_IMAGE_REVISION", "not supplied"),
            "image_inputs_sha256": digest(image_inputs), "python": platform.python_version(),
            "platform": platform.platform(), "architecture": platform.machine(),
            "packages": {name: importlib.metadata.version(name) for name in (
                "arsia-native-intake", "psycopg", "psycopg-binary", "openpyxl", "pytest")},
        }
        result["tables_before"] = empty_tables()
        result["audit_before"] = common.audit()
        marker = secrets.token_hex(16)
        from psycopg import sql
        with common.connect("owner") as connection:
            connection.execute(sql.SQL("ALTER DATABASE arsia SET arsia.test_run = {}").format(sql.Literal(marker)))
        with common.connect("loader") as connection:
            row = connection.execute("SELECT current_user,session_user,current_setting('arsia.test_run'), "
                                     "current_setting('server_encoding'),current_setting('TimeZone')").fetchone()
            require(row == ("arsia_loader", "arsia_loader", marker, "UTF8", "UTC"),
                    "The loader identity, encoding, timezone or test marker is wrong")
        selections = {
            "e-synthetic": selection(common.ROOT / "docker/team/vendor/e/acceptance/e/run_database.py", "SYNTHETIC"),
            "b-recovery": selection(common.ROOT / "tools/verify_b14_postgres.py", "TESTS"),
            "ui-build": EXTRA_TESTS,
            "runner-guards": GUARD_TESTS,
        }
        result["source_lock"] = json.loads((common.ROOT / "docker/team/sources.json").read_text(encoding="utf-8"))
        result["runner_sha256"] = digest(Path(__file__))
        config = output / "pytest.ini"
        config.write_text("[pytest]\n", encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="arsia-compose-acceptance-") as temporary:
            reference = Path(temporary) / "reference"
            result["tested_files"] = copy_reference(reference)
            common.write(output / "inputs.json", {key: result[key] for key in (
                "source_lock", "runner_sha256", "runtime", "installed_package", "tested_files", "database")})
            for name, tests in selections.items():
                directory = output / name
                directory.mkdir()
                env = environment(directory, marker)
                command = pytest_command(reference, config, directory, tests)
                common.write(directory / "command.json", {"argv": command, "cwd": str(directory),
                                                           "pythonpath_removed": "PYTHONPATH" not in env})
                completed = subprocess.run(command, cwd=directory, env=env, text=True,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                (directory / "pytest.log").write_text(redact(completed.stdout), encoding="utf-8")
                report = directory / "pytest.xml"
                if report.is_file():
                    report.write_text(redact(report.read_text(encoding="utf-8")), encoding="utf-8")
                tests_result = test_results(report, tests)
                result["runs"][name] = {"pytest_exit_code": completed.returncode, **tests_result}
                common.write(directory / "summary.json", result["runs"][name])
                require(completed.returncode == 0 and not any(tests_result[key] for key in ("failures", "errors", "skipped")),
                        "Acceptance tests failed or skipped: " + name)
                empty_tables()
        result["status"] = "passed"
        result["exit_code"] = 0
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": redact(str(error))}
    finally:
        if checked_target:
            try:
                result["audit_after"] = common.audit()
                result["tables_after"] = empty_tables()
                with common.connect("owner") as connection:
                    locks = connection.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' "
                                               "AND database=(SELECT oid FROM pg_database WHERE datname=current_database())").fetchone()[0]
                require(locks == 0, "Acceptance left advisory locks")
                result["advisory_locks_after"] = locks
            except Exception as error:
                result.update(status="failed", exit_code=1)
                result["final_check_error"] = {"type": type(error).__name__, "message": redact(str(error))}
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        result["cleanup"] = {"tables_empty": result.get("tables_after") == dict.fromkeys(TABLES, 0),
                             "container_removed": False,
                             "scope": "Compose owns the acceptance service lifecycle; this runner cannot call Docker"}
        result["totals"] = {key: sum(run[key] for run in result["runs"].values())
                            for key in ("tests", "passed", "failures", "errors", "skipped")}
        result["evidence_files"] = [{"path": str(path.relative_to(output)), "sha256": digest(path),
                                     "bytes": path.stat().st_size}
                                    for path in sorted(output.rglob("*")) if path.is_file()]
        common.write(output / "receipt.json", result)
    return result
