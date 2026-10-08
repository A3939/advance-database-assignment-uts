"""Offline harness checks only. These never constitute real-model evidence."""
import ast
import hashlib
import os
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from verify_real_model_recovery import RecoverySession, evaluate_recovery, inject_name_error, main, test_database as temporary_database


def session(tmp_path):
    value = RecoverySession.__new__(RecoverySession)
    value.injection = None
    value.model_input_receipts = []
    value.work_dir = tmp_path
    value.usage = {"model_calls": 2, "tool_calls": 3, "correction_count": 0}
    value.code, value.validated, value.registered, value.sample_gate = "", None, None, None
    value.contract = {"contract_version": "canonical-v2"}
    return value


def test_injection_is_one_name_at_function_entry_and_preserves_docstring():
    original = 'from math import sqrt\ndef adapt(ctx):\n    "A docstring"\n    for row in []:\n        ctx.emit(row)\n'
    output = inject_name_error(original, "arsia_recovery_unique")
    tree = ast.parse(output)
    adapt = tree.body[1]
    assert ast.get_docstring(adapt) == "A docstring"
    assert isinstance(adapt.body[1].value, ast.Name)
    assert adapt.body[1].value.id == "arsia_recovery_unique"
    assert output.count("arsia_recovery_unique") == 1
    assert isinstance(adapt.body[2], ast.For)
    with pytest.raises(ValueError):
        inject_name_error(original, "adapt")


def test_subclass_injects_exactly_once_and_preserves_both_code_versions(tmp_path):
    value = session(tmp_path)
    original = "def adapt(ctx):\n    pass\n"
    first = value.write_code(original, "model wrote adapter")
    injected = value.code
    repaired = value.write_code(original, "model removed unknown name after diagnostics")
    assert value.injection["count"] == 1
    assert value.injection["original_sha256"] == hashlib.sha256(original.encode()).hexdigest()
    assert first["code_sha256"] != repaired["code_sha256"]
    assert value.injection["symbol"] in injected
    assert value.injection["symbol"] not in value.code
    assert len(list((tmp_path / "adapter-versions").glob("*.py"))) == 2
    assert (tmp_path / "model-original-before-injection.py").read_text() == original


def test_first_run_python_executes_the_injected_bytes_not_stale_original(tmp_path):
    value = session(tmp_path)
    with patch("arsia_pipeline.agent.AgentSession.execute_tool", side_effect=lambda name,args: args) as base:
        result = value.execute_tool("run_python", {"code": "def adapt(ctx):\n    pass", "mode": "sample"})
    assert value.injection["symbol"] in result["code"]
    assert result["code"] == value.code
    base.assert_called_once()


def trace():
    def step(name, result, kind="tool"):
        return {"kind": kind, "name": name, "status": "succeeded", "result": result}
    admission = {"status": "admitted", "adapter_sha256": "fixed", "image": "sha256:image", "trusted_implementation": {"qa": "hash"}}
    rows = [step("responses", {"id": "real-provider-response-1", "model": "real-model"}, "model"),
            step("run_adapter", {"mode": "sample", "status": "failed", "code_sha256": "bad", "error": {"type": "NameError"}}),
            step("responses", {"id": "real-provider-response-2", "model": "real-model"}, "model"),
            step("read_adapter", {"code": "bounded"}),
            step("patch_adapter", {"code_sha256": "fixed"}),
            step("run_adapter", {"mode": "sample", "status": "succeeded", "code_sha256": "fixed"}),
            step("validate_candidate", {"status": "sample_only", "admission": {"adapter_sha256": "fixed"}}),
            step("run_adapter", {"mode": "full", "status": "succeeded", "code_sha256": "fixed"}),
            step("validate_candidate", {"status": "validated", "admission": admission}),
            step("register_adapter", {"code_sha256": "fixed"}),
            step("publish_candidate", {"status": "accepted_for_atomic_publication"})]
    return rows, {"count": 1, "injected_sha256": "bad"}, admission


def test_ordered_checker_requires_failed_sample_model_inspection_repair_and_full_qa():
    rows, injection, admission = trace()
    assert evaluate_recovery(rows, injection, admission)["passed"]
    for index in (1, 2, 3, 6, 7, 8, 9):
        assert not evaluate_recovery(rows[:index] + rows[index+1:], injection, admission)["passed"]
    assert not evaluate_recovery(rows, {**injection, "count": 2}, admission)["passed"]


def test_checker_does_not_call_identical_or_unrelated_code_a_repair():
    rows, injection, admission = trace()
    rows[5]["result"]["code_sha256"] = "bad"
    assert not evaluate_recovery(rows, injection, admission)["passed"]
    rows, injection, admission = trace()
    rows[7]["result"]["code_sha256"] = "different-full-code"
    assert not evaluate_recovery(rows, injection, admission)["passed"]


def test_direct_patch_is_valid_when_actual_next_model_input_contains_failure():
    rows, injection, admission = trace()
    rows[1]["result"]["run_id"] = "actual-failed-run"
    rows[2]["arguments"] = {"model_call": 2}
    rows = [row for row in rows if row["name"] != "read_adapter"]
    receipts = [{"model_call": 2, "sha256": "saved-actual-wire-hash", "structured_failed_sample_run_ids": ["actual-failed-run"]}]
    result = evaluate_recovery(rows, injection, admission, receipts)
    assert result["passed"]
    assert result["diagnostic_consumption"] == {"explicit_inspection_tool": False, "structured_failure_in_actual_model_input": True}
    assert not evaluate_recovery(rows, injection, admission, [{**receipts[0], "model_call": 1}])["passed"]


def test_actual_wire_receipt_detects_structured_nameerror_without_inventing_inspection(tmp_path):
    import json
    value = session(tmp_path)
    value.injection = {"injected_sha256": "bad"}
    run = {"run_id": "run-1", "status": "failed", "error": {"type": "NameError"}, "code_sha256": "bad"}
    value.runs = {"run-1": run}
    messages = [{"type": "function_call_output", "output": json.dumps(run), "call_id": "call-1"}]
    with patch("arsia_pipeline.agent.AgentSession.wire_messages", return_value=messages):
        assert value.wire_messages() is messages
    receipt = value.model_input_receipts[0]
    assert receipt["structured_failed_sample_run_ids"] == ["run-1"]
    assert hashlib.sha256(Path(receipt["path"]).read_bytes()).hexdigest() == receipt["sha256"]


def test_database_context_only_creates_and_drops_its_new_marked_database(tmp_path):
    original = {"database": "arsia_imports_live", "dsn": "dbname=arsia_imports_live host=localhost", "instance_id": "live"}
    calls = []
    class Connection:
        def __init__(self, config): self.config = config
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, statement): calls.append((self.config["database"], str(statement)))
    prior = os.environ.get("ARSIA_IMPORT_CONFIG")
    receipt = {}
    with patch("verify_real_model_recovery.ROOT", tmp_path), \
         patch("verify_real_model_recovery.store.connect", side_effect=Connection), \
         patch("verify_real_model_recovery.store.initialize") as initialize:
        with temporary_database(original, receipt) as config:
            assert config["database"].startswith("arsia_imports_test_recovery_")
            assert config["instance_id"] != original["instance_id"]
            assert Path(os.environ["ARSIA_IMPORT_CONFIG"]).exists()
            assert "arsia_imports_test_recovery_" in config["dsn"]
        initialize.assert_called_once_with(config)
    assert os.environ.get("ARSIA_IMPORT_CONFIG") == prior
    assert receipt["test_database"]["dropped"]
    assert len(calls) == 2
    assert "CREATE DATABASE" in calls[0][1] and "DROP DATABASE" in calls[1][1]
    assert all(config["database"] in statement for _,statement in calls)
    assert not list(tmp_path.glob("*.json"))


def test_database_initialization_failure_never_drops_unverified_database(tmp_path):
    original = {"database": "arsia_imports_live", "dsn": "dbname=arsia_imports_live", "instance_id": "live"}
    calls = []
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, statement): calls.append(str(statement))
    receipt = {}
    with patch("verify_real_model_recovery.ROOT", tmp_path), \
         patch("verify_real_model_recovery.store.connect", return_value=Connection()), \
         patch("verify_real_model_recovery.store.initialize", side_effect=RuntimeError("wrong marker")):
        with pytest.raises(RuntimeError, match="wrong marker"):
            with temporary_database(original, receipt):
                pytest.fail("Initialization unexpectedly succeeded")
    assert len(calls) == 1 and "CREATE DATABASE" in calls[0]
    assert receipt["test_database"]["dropped"] is False


def test_command_requires_explicit_opt_in_before_any_runtime_access():
    with patch("verify_real_model_recovery.read_config", side_effect=AssertionError("Runtime was read")):
        with pytest.raises(SystemExit) as exc:
            main(["--source-job-id", "00000000-0000-0000-0000-000000000001"])
        assert exc.value.code == 2


def test_import_and_help_do_not_invoke_gateway_database_or_executor():
    with patch("verify_real_model_recovery.read_config", side_effect=AssertionError("Runtime was read")), \
         patch("arsia_pipeline.agent.gateway", side_effect=AssertionError("Model was called")), \
         patch("arsia_pipeline.store.connect", side_effect=AssertionError("Database was opened")):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0
