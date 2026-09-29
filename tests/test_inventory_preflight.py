"""Catch inventory drift before building or starting the Docker runtime."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('inventory_preflight', ROOT / 'tools/check_inventory.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(root):
    (root / 'config').mkdir()
    (root / 'docker/team').mkdir(parents=True)
    (root / 'runtime.py').write_text('original')
    record = {'path': 'runtime.py', 'sha256': hashlib.sha256(b'original').hexdigest()}
    for name in ('build', 'd09'):
        (root / f'config/{name}-inventory.json').write_text(json.dumps({'code_files': [record]}))
    (root / 'docker/team/sources.json').write_text(json.dumps({
        'files': [record], 'overlays': [{**record, 'path': 'generated.py', 'source_path': 'runtime.py'}]}))


def test_repository_inventory_matches():
    assert module.check_inventory(ROOT) == []


def test_overlay_sources_checked_without_generated_targets(tmp_path):
    fixture(tmp_path)
    assert module.check_inventory(tmp_path) == []
    (tmp_path / 'generated.py').write_text('conflict')
    assert any('overlay target already exists' in e for e in module.check_inventory(tmp_path))


def test_drift_reports_every_inventory_and_does_not_modify(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'runtime.py').write_text('changed')
    errors = module.check_inventory(tmp_path)
    assert len(errors) == 4
    assert all('checksum mismatch' in e for e in errors)
    assert (tmp_path / 'runtime.py').read_text() == 'changed'


def test_missing_files_and_inventory(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'runtime.py').unlink()
    (tmp_path / 'config/d09-inventory.json').unlink()
    errors = module.check_inventory(tmp_path)
    assert any('missing required inventory' in e for e in errors)
    assert any('missing runtime.py' in e for e in errors)


def test_invalid_json_and_unsafe_paths(tmp_path):
    fixture(tmp_path)
    (tmp_path / 'config/build-inventory.json').write_text('{broken')
    (tmp_path / 'config/d09-inventory.json').write_text(json.dumps({
        'code_files': [{'path': '../outside', 'sha256': '0' * 64}]}))
    errors = module.check_inventory(tmp_path)
    assert any('cannot validate' in e for e in errors)
    assert any('unsafe file path' in e for e in errors)
