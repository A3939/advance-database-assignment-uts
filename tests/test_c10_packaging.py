"""Read C10 and its C06 dependency from a wheel outside the build checkout."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_wheel_resources_outside_source(tmp_path):
    source = tmp_path / "source"
    shutil.copytree(
        ROOT / "src",
        source / "src",
        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
    )
    shutil.copyfile(ROOT / "pyproject.toml", source / "pyproject.toml")
    wheels = tmp_path / "wheels"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            str(source),
            "-w",
            str(wheels),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run([sys.executable, "-m", "venv", str(tmp_path / "venv")], check=True)
    python = tmp_path / "venv/bin/python"
    subprocess.run(
        [str(python), "-m", "pip", "install", str(next(wheels.glob("*.whl")))],
        check=True,
        capture_output=True,
    )
    names = [
        "c10_qa03_expectation.sql",
        "c10_qa03_projected.sql",
        "c10_qa04_auxiliary.sql",
        "c10_qa05_semantics.sql",
        "c10_qa07_location.sql",
        "c06_vic_person_checks.sql",
    ]
    expected = {
        n: hashlib.sha256((ROOT / "src/arsia_c/sql" / n).read_bytes()).hexdigest() for n in names
    }
    shutil.rmtree(source)
    outside = tmp_path / "outside"
    outside.mkdir()
    script = """
import hashlib,json,sys
from pathlib import Path
from arsia_c import qa,person_checks
from arsia_ingest.components import bindings
from arsia_ingest.runner import BuildModules, ModuleBinding
from importlib.resources import files
from arsia_c.restricted_person import restricted_inputs
assert Path(qa.__file__).is_relative_to(Path(sys.prefix))
expected=json.loads(sys.argv[1])
binding=bindings()["qa_c"]
assert type(binding) is ModuleBinding and binding.callback is qa.runner_callback
assert binding.version==qa.PRODUCER_VERSION and binding.code_path=="src/arsia_c/qa.py"
assert BuildModules(**bindings()).publish is None
for entry in json.loads(sys.argv[2]):
    parts=Path(entry["path"]).parts
    if parts[0]=="src":
        data=files(parts[1]).joinpath(*parts[2:]).read_bytes()
        assert hashlib.sha256(data).hexdigest()==entry["sha256"]
for name,digest in expected.items():
    text=qa._sql(name)
    assert text.strip() and hashlib.sha256(text.encode()).hexdigest()==digest
assert person_checks.SQL_PATH.read_text(encoding='utf-8')==qa._sql('c06_vic_person_checks.sql')
assert json.loads(person_checks.POLICY_PATH.read_text(encoding='utf-8'))['mapping_version']
spec, policy=restricted_inputs()
assert spec['profile_id']==policy['profile_id'] and spec['protocol_version']=='team-v1.1-vic-r1'
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    subprocess.run(
        [str(python), "-I", "-c", script, json.dumps(expected),
         json.dumps(json.loads((ROOT / "config/cd-inventory.json").read_text(encoding="utf-8"))["code_files"])],
        cwd=outside,
        env=env,
        check=True,
        capture_output=True,
    )
