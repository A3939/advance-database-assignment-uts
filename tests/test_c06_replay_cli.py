"""The replay command resolves inputs without relying on the current directory."""
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/replay_c06_cases.py"


def run_tool(arguments, directory):
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run([sys.executable, str(TOOL), *arguments], cwd=directory,
                          env=environment, capture_output=True, text=True, timeout=20)


def test_help_works_outside_the_checkout_without_a_database(tmp_path):
    result = run_tool(["--help"], tmp_path)
    assert result.returncode == 0
    assert "--input-config" in result.stdout


def test_explicit_input_config_rejects_lfs_pointers_before_connecting(tmp_path):
    inputs = tmp_path / "inputs with spaces"
    inputs.mkdir()
    config = json.loads((ROOT / "config/native-inputs.json").read_text())
    for resource in config["resources"]:
        path = inputs / Path(resource["path"]).name
        path.write_text("version https://git-lfs.github.com/spec/v1\n"
                        "oid sha256:" + "0" * 64 + "\nsize 123\n")
        resource["path"] = path.name
    config_path = inputs / "native-inputs.json"
    config_path.write_text(json.dumps(config))
    output = tmp_path / "receipt.json"
    result = run_tool(["--input-config", str(config_path), "--evidence", str(output)], tmp_path)
    assert result.returncode != 0
    assert "official_vic_accident is a Git LFS pointer" in result.stderr
    assert not output.exists()
