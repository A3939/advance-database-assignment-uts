"""Load C03 SQL from a wheel installed outside the source checkout."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import pytest

ROOT = Path(__file__).resolve().parents[1]
SQL_NAMES = (
    "c03_projection_tables.sql",
    "c03_nsw_relationship_check.sql",
    "c03_nsw_year_check.sql",
    "c03_nsw_month_check.sql",
    "c03_nsw_semantic_check.sql",
    "c03_nsw_unit_check.sql",
    "c03_nsw_crash_insert.sql",
    "c03_nsw_unit_insert.sql",
    "c03_nsw_projection_check.sql",
)


@pytest.mark.parametrize("name", SQL_NAMES)
def test_packaged_sql_matches_reviewed_sql(name):
    assert (ROOT / "src/arsia_c/projections/sql" / name).read_bytes() == (
        ROOT / "sql/projections" / name
    ).read_bytes()


def _run(args, cwd):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_installed_wheel_loads_all_c03_sql(tmp_path):
    source = tmp_path / "build-source"
    source.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", source)
    shutil.copytree(
        ROOT / "src", source / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    wheels = tmp_path / "wheels"
    _run([
        sys.executable, "-m", "pip", "wheel", "--no-deps",
        "--no-build-isolation", "--no-index", "--wheel-dir", str(wheels),
        str(source),
    ], tmp_path)
    wheel, = wheels.glob("*.whl")

    env = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(env)
    python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    _run([
        str(python), "-I", "-m", "pip", "install", "--no-deps", "--no-index",
        "--no-compile", str(wheel),
    ], tmp_path)

    # Remove the build sources so the child can only use the installed package.
    shutil.rmtree(source)
    outside = tmp_path / "outside"
    outside.mkdir()
    script = """
import hashlib, json, pathlib, sys, sysconfig
from arsia_c.projections import nsw
site = pathlib.Path(sysconfig.get_path('purelib')).resolve()
assert pathlib.Path(nsw.__file__).resolve().is_relative_to(site), nsw.__file__
assert sys.prefix != sys.base_prefix
names = json.loads(sys.argv[1])
print(json.dumps({
    name: hashlib.sha256(nsw._load_sql(name).encode('utf-8')).hexdigest()
    for name in names
}))
"""
    actual = json.loads(_run([
        str(python), "-I", "-c", script, json.dumps(SQL_NAMES),
    ], outside))
    expected = {
        name: hashlib.sha256((ROOT / "sql/projections" / name).read_bytes()).hexdigest()
        for name in SQL_NAMES
    }
    assert actual == expected
