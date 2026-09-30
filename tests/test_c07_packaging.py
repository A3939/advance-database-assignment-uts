"""Read C07 SQL from an installed wheel outside the source checkout."""

from pathlib import Path
import shutil
import subprocess
import sys

from arsia_c.node_location import _load_node_sql

ROOT = Path(__file__).resolve().parents[1]


def test_sql_resource_matches_reviewed_sql():
    expected = ROOT / "src/arsia_c/sql/c07_vic_node_observations.sql"
    assert _load_node_sql() == expected.read_text(encoding="utf-8")


def test_installed_wheel_reads_node_sql(tmp_path):
    source = tmp_path / "build-source"
    source.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", source)
    shutil.copytree(ROOT / "src", source / "src", ignore=shutil.ignore_patterns(
        "__pycache__", "*.egg-info",
    ))
    wheels = tmp_path / "wheels"
    subprocess.run([
        sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
        "--no-index", "--wheel-dir", str(wheels), str(source),
    ], check=True, capture_output=True, text=True)
    wheel, = wheels.glob("*.whl")
    installed = tmp_path / "installed"
    subprocess.run([
        sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
        "--no-compile", "--target", str(installed), str(wheel),
    ], check=True, capture_output=True, text=True)
    script = """
import pathlib, sys
sys.path.insert(0, sys.argv[1])
from arsia_c import node_location
assert pathlib.Path(node_location.__file__).is_relative_to(sys.argv[1])
sys.stdout.write(node_location._load_node_sql())
"""
    result = subprocess.run([
        sys.executable, "-I", "-c", script, str(installed),
    ], cwd=tmp_path, check=True, capture_output=True, text=True)
    expected = ROOT / "src/arsia_c/sql/c07_vic_node_observations.sql"
    assert result.stdout == expected.read_text(encoding="utf-8")
