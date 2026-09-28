"""C04/C05 must also resolve their frozen inputs and SQL from an installed wheel."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_c45_installed_wheel_resources(tmp_path):
    source = tmp_path / "build-source"
    source.mkdir()
    shutil.copy2(ROOT / "pyproject.toml", source)
    shutil.copytree(
        ROOT / "src",
        source / "src",
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.egg-info",
        ),
    )
    wheels = tmp_path / "wheels"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--no-index",
            "--wheel-dir",
            str(wheels),
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    (wheel,) = wheels.glob("*.whl")
    installed = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--no-index",
            "--no-compile",
            "--target",
            str(installed),
            str(wheel),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    script = """
import hashlib, json, pathlib, sys
sys.path.insert(0, sys.argv[1])
from arsia_c.projections import source_contracts as sc
assert pathlib.Path(sc.__file__).is_relative_to(sys.argv[1])
names = json.loads(sys.argv[2])
out = {name: hashlib.sha256(sc.sql(name).encode('utf-8')).hexdigest() for name in names}
out['vic'] = sc.vic_definitions()
out['qld'] = sc.qld_definitions()
print(json.dumps(out))
"""
    names = [p.name for p in (ROOT / "src/arsia_c/sql").glob("*.sql")]
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            script,
            str(installed),
            json.dumps(names),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    import hashlib
    from arsia_c.projections.source_contracts import vic_definitions, qld_definitions

    actual = json.loads(result.stdout)
    for name in names:
        reviewed = [ROOT / "sql" / folder / name for folder in ("projections", "qa")]
        reviewed = [path for path in reviewed if path.is_file()]
        assert len(reviewed) == 1, name
        assert (
            actual[name]
            == hashlib.sha256(
                reviewed[0].read_bytes()
            ).hexdigest()
        )
    assert actual["vic"] == vic_definitions()
    assert actual["qld"] == qld_definitions()
    for name in (
        "vic-restricted-inputs-v1.json",
        "vic-restricted-use-v1.json",
        "c05-qld-official-v1.json",
    ):
        assert (ROOT / "config" / name).read_bytes() == (
            ROOT / "src/arsia_c/config" / name
        ).read_bytes()
