"""Unit fault checks for the Compose runner; these do not simulate database acceptance."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class AcceptanceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.executor = patch.dict(os.environ, {"ARSIA_EXECUTOR": "Acceptance unit tests"})
        self.executor.start()
        self.addCleanup(self.executor.stop)
        self.common = SimpleNamespace(ROOT=self.directory / "project", dsn=Mock(return_value="unit-test-dsn"),
                                      connect=Mock(), initialize=Mock(), check_installation=Mock(),
                                      table_counts=Mock(), audit=Mock(return_value={"status": "passed"}))
        def write(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value), encoding="utf-8")
        self.common.write = write
        package = ModuleType("acceptance_guard_unit")
        package.__path__ = []
        package.common = self.common
        self.modules = patch.dict(sys.modules, {"acceptance_guard_unit": package})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("acceptance_guard_unit.acceptance", ROOT / "docker/team/acceptance.py")
        self.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.runner)

    def conninfo(self, **options):
        module = ModuleType("psycopg.conninfo")
        module.conninfo_to_dict = lambda _: options
        return patch.dict(sys.modules, {"psycopg.conninfo": module})

    def test_development_or_remote_database_is_rejected_before_connection(self):
        for options in ({"host": "db", "dbname": "arsia"},
                        {"host": "example.org", "dbname": "arsia"},
                        {"host": "acceptance-db", "dbname": "development"}):
            with self.subTest(options=options), self.conninfo(**options):
                with self.assertRaisesRegex(ValueError, "separate acceptance-db"):
                    self.runner.target_guard()
        self.common.connect.assert_not_called()

    def test_wrong_server_marker_or_owner_is_rejected(self):
        for row in (("arsia", "development", "arsia_owner", "arsia_owner"),
                    ("arsia", None, "arsia_owner", "arsia_owner"),
                    ("arsia", "acceptance", "postgres", "postgres")):
            with self.subTest(row=row), self.conninfo(host="acceptance-db", dbname="arsia"):
                connection = self.common.connect.return_value.__enter__ = Mock()
                connection.return_value.execute.return_value.fetchone.return_value = row
                self.common.connect.return_value.__exit__ = Mock(return_value=False)
                with self.assertRaisesRegex(ValueError, "identity or server marker"):
                    self.runner.target_guard()

    def test_all_seventeen_integer_zero_counts_are_required(self):
        original = dict.fromkeys(self.runner.TABLES, 0)
        for fault in ("rows", "missing", "boolean"):
            counts = dict(original)
            if fault == "missing":
                counts.pop("raw.record")
            else:
                counts["raw.record"] = 1 if fault == "rows" else False
            with self.subTest(fault=fault):
                self.common.table_counts.return_value = counts
                with self.assertRaisesRegex(ValueError, "seventeen application tables"):
                    self.runner.empty_tables()

    def test_literal_selection_does_not_execute_the_file(self):
        path = self.directory / "selection.py"
        path.write_text("raise RuntimeError('must not run')\nTESTS = ('test_one.py',)\n", encoding="utf-8")
        self.assertEqual(("test_one.py",), self.runner.selection(path, "TESTS"))
        for value in ("('test_one.py', 'test_one.py')", "('../test_one.py',)", "tuple(['test_one.py'])"):
            with self.subTest(value=value):
                path.write_text("TESTS = " + value, encoding="utf-8")
                with self.assertRaises(ValueError):
                    self.runner.selection(path, "TESTS")

    def junit(self, cases):
        path = self.directory / "unit-junit.xml"
        path.write_text("<testsuites><testsuite>" + cases + "</testsuite></testsuites>", encoding="utf-8")
        return path

    def test_junit_counts_real_cases_and_exposes_failures_and_skips(self):
        path = self.junit('<testcase classname="test_one" name="passes"/>'
                          '<testcase classname="test_one" name="fails"><failure/></testcase>'
                          '<testcase classname="test_two" name="skips"><skipped/></testcase>')
        result = self.runner.test_results(path, ("test_one.py", "test_two.py"))
        self.assertEqual((3, 1, 1, 1), tuple(result[key] for key in ("tests", "passed", "failures", "skipped")))
        self.assertEqual(["test_one::fails"], result["failed_test_names"])
        self.assertEqual(["test_two::skips"], result["skipped_test_names"])

    def test_missing_or_unexpected_junit_modules_cannot_pass(self):
        for cases in ('', '<testcase classname="test_other" name="passes"/>',
                      '<testcase classname="test_one" name="passes"/>'):
            with self.subTest(cases=cases):
                with self.assertRaises(ValueError):
                    self.runner.test_results(self.junit(cases), ("test_one.py", "test_two.py"))

    def test_refused_target_writes_failure_without_initializing_or_running_tests(self):
        output = self.directory / "refused-run"
        with self.conninfo(host="db", dbname="arsia"), patch.object(self.runner.subprocess, "run") as process:
            result = self.runner.run(output)
        self.assertEqual(("failed", 1), (result["status"], result["exit_code"]))
        self.assertFalse(result["independent_member_signoff"])
        self.assertEqual({}, result["runs"])
        self.assertEqual("failed", json.loads((output / "receipt.json").read_text())["status"])
        process.assert_not_called()
        self.common.initialize.assert_not_called()
        self.common.audit.assert_not_called()

    def test_existing_output_is_preserved(self):
        with self.assertRaisesRegex(ValueError, "new acceptance output"):
            self.runner.run(self.directory)
        self.common.connect.assert_not_called()

    def test_missing_executor_is_refused_before_database_access(self):
        for index, value in enumerate(("", "  ", "REPLACE_WITH_YOUR_NAME")):
            with self.subTest(value=value), patch.dict(os.environ, {"ARSIA_EXECUTOR": value}):
                result = self.runner.run(self.directory / str(index))
                self.assertEqual("failed", result["status"])
                self.assertIn("actual person", result["error"]["message"])
        self.common.connect.assert_not_called()
        self.common.initialize.assert_not_called()

    def test_reference_keeps_the_inventory_linked_d09_receipt(self):
        source = self.common.ROOT
        for directory in ("src", "tests", "tools", "config", "sql", "docs/evidence/d09", "docker/team"):
            (source / directory).mkdir(parents=True, exist_ok=True)
        (source / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (source / "config/d09-inventory.json").write_text(json.dumps({
            "acceptance": {"evidence": "docs/evidence/d09"}}), encoding="utf-8")
        summary = source / "docs/evidence/d09/summary.json"
        summary.write_text('{"unit_fixture": true}\n', encoding="utf-8")
        target = self.directory / "reference"
        copied = self.runner.copy_reference(target)
        self.assertEqual(summary.read_bytes(), (target / "docs/evidence/d09/summary.json").read_bytes())
        self.assertIn("docs/evidence/d09/summary.json", {row["path"] for row in copied})

    def test_external_config_keeps_module_fixtures_and_junit_identities_separate(self):
        reference = self.directory / "reference"
        tests = reference / "tests"
        tests.mkdir(parents=True)
        output = self.directory / "outside-source"
        output.mkdir()
        config = output / "pytest.ini"
        config.write_text("[pytest]\n", encoding="utf-8")
        (tests / "test_a.py").write_text(
            "import pytest\n@pytest.fixture\ndef connection():\n    return []\n"
            "@pytest.fixture(autouse=True)\ndef transaction(connection):\n"
            "    connection.append('in_transaction')\n"
            "def test_a(connection):\n    assert connection == ['in_transaction']\n", encoding="utf-8")
        (tests / "test_b.py").write_text(
            "import pytest\n@pytest.fixture\ndef connection():\n    return []\n"
            "def test_b(connection):\n    assert connection == []\n", encoding="utf-8")
        selected = ("test_a.py", "test_b.py")
        command = self.runner.pytest_command(reference, config, output, selected)
        env = {key: value for key, value in os.environ.items() if not key.startswith("PYTHON")}
        process = subprocess.run(command, cwd=output, env=env, capture_output=True, text=True)
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        result = self.runner.test_results(output / "pytest.xml", selected)
        self.assertEqual(2, result["passed"])
        self.assertEqual({"test_a", "test_b"}, set(result["modules"]))


if __name__ == "__main__":
    unittest.main()
