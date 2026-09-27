"""The installed build uses real bindings and a complete S0 inventory."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from arsia_ingest.build import FP1, build_inventory, build_modules, fp1_sql, s0_request
from arsia_ingest.manifest import COMPONENTS, FrozenManifest, s0_definitions
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import _bindings

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_covers_installed_runtime_and_real_bindings():
    inventory = build_inventory(ROOT)
    assert set(inventory['components']) == set(COMPONENTS)
    paths = {p for group in inventory['components'].values() for p in group}
    runtime = {str(p.relative_to(ROOT)) for p in (ROOT / 'src').rglob('*')
               if p.suffix in {'.py', '.sql', '.json'}}
    assert runtime <= paths
    assert len(inventory['schema_files']) == 11
    modules = build_modules()
    _bindings(modules, FP1, inventory)
    assert modules.publish.callback.__module__ == 'arsia_ingest.publication'
    assert modules.qa_c.callback.__module__ == 'arsia_c.qa'
    with pytest.raises(IntakeError, match='unavailable'):
        _bindings(replace(modules, publish=None), FP1, inventory)
    with pytest.raises(IntakeError, match='FP1'):
        _bindings(modules, None, inventory)


def test_packaged_fp1_matches_e_original():
    assert fp1_sql().encode('utf-8') == (ROOT / FP1.code_path).read_bytes()
    assert 'GRANT EXECUTE' in fp1_sql()


def test_inventory_rejects_changed_bytes(tmp_path):
    inventory = build_inventory(ROOT)
    paths = {p for group in inventory['components'].values() for p in group}
    paths.update(inventory['schema_files'])
    paths.add('config/build-inventory.json')
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    target = tmp_path / 'src/arsia_ingest/publication.py'
    target.write_bytes(target.read_bytes() + b'\n# Changed after review.\n')
    with pytest.raises(IntakeError, match='differ'):
        build_inventory(tmp_path)


def test_real_s0_factory_freezes_sources_rules_and_all_components(tmp_path):
    prepared = prepare(ROOT / 'tests/fixtures/s0/config.json', tmp_path / 'intake')
    request = s0_request(connect=lambda: None, project_root=ROOT,
                         prepared_run=prepared['run_dir'], evidence_root=tmp_path / 'build')
    manifest = request['manifest']
    assert type(manifest) is FrozenManifest
    value = manifest.as_dict()
    definitions = s0_definitions(ROOT / 'tests/fixtures/s0/contract.json')
    expected = [dict(row, resource_ids=sorted(row['resource_ids'])) for row in definitions['sources']]
    assert value['sources'] == sorted(expected, key=lambda r: r['source_id'])
    assert value['analysis'] == {'year_from': 2020, 'year_to': 2024}
    assert len(value['rules']['severity']) == 12
    assert sum(r['severity_code'] == '__MISSING__' for r in value['rules']['severity']) == 3
    assert len(value['files']) == 7
    assert request['supported_mappings'] == definitions['mappings']
    hashes = {r['path']: r['sha256'] for r in value['rules']['code_files']}
    assert hashes[FP1.code_path] == hashlib.sha256((ROOT / FP1.code_path).read_bytes()).hexdigest()
    assert 'src/arsia_ingest/publication.py' in hashes
    assert value['dataset_kind'] == 'synthetic'
    declared = json.loads((ROOT / 'config/build-inventory.json').read_text(encoding='utf-8'))
    assert declared['complete_build'] is True and declared['final_platform'] is False
