"""CLI outcome checks; database recovery itself has separate PostgreSQL tests."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from arsia_ingest import recovery


@pytest.mark.parametrize("resolution,code,status", [
    ("succeeded", 0, "passed"), ("failed", 0, "passed"), ("not_registered", 0, "passed"),
    ("busy", 2, "unresolved"), ("unknown_commit", 3, "unresolved"),
])
def test_recovery_cli_keeps_native_resolution_and_exit_code(tmp_path, monkeypatch, resolution, code, status):
    path = Path(__file__).resolve().parents[1] / "docker/team/cli.py"
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("team_cli_recovery_unit", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "Path", lambda value: tmp_path if str(value) == "/evidence" else Path(value))
    monkeypatch.setattr(cli, "info", lambda: {"unit_test": "no database or image check"})
    monkeypatch.setenv("ARSIA_EXECUTOR", "CLI unit test")
    monkeypatch.setattr(recovery, "recover_run", lambda **kwargs: recovery.RecoveryResult({"resolution": resolution}))
    output = tmp_path / "result"
    monkeypatch.setattr(sys, "argv", ["cli", "recover", "--output", str(output),
                                      "--run-dir", str(tmp_path / "saved-run")])
    assert cli.main() == code
    result = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
    assert result["result"]["resolution"] == resolution
    assert result["status"] == status and result["exit_code"] == code
    assert result["independent_member_signoff"] is False and result["final_platform_accepted"] is False
