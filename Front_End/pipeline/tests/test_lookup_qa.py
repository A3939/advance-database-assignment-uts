"""Physical lookup replay and binding tests; none grants semantic admission."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from arsia_pipeline import adapter_reuse as reuse
from arsia_pipeline.adapter_sdk import AdapterContext
from arsia_pipeline.errors import NeedsInput, UnsupportedCapability, ValidationFailure
from arsia_pipeline.lookup_projection import LookupProjection
from arsia_pipeline.registry import execution_contract_hash
from arsia_pipeline.table_plan import input_resources
from arsia_pipeline.transform_plan import contract_plans
from arsia_pipeline.trusted_qa import semantic_contract, validate_candidate, validate_contract
from arsia_pipeline.update_compatibility import require_compatible_update
from test_lookup_plan import admitted
from test_lookup_projection import bundle


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def candidate(tmp_path, mode='sample', configure=None):
    c, files = bundle(tmp_path)
    if configure:
        configure(c, files)
    output = tmp_path / 'output'
    output.mkdir()
    ctx = AdapterContext(c, files, output, mode)
    try:
        for resource in c['resources']:
            for locator, row in ctx.iter_rows(resource['role']):
                ctx.emit(resource['grain'], ctx.project(resource['role'], locator, row))
    finally:
        ctx.close()
    run = {'status': 'succeeded', 'mode': mode, 'run_id': 'lookup-test',
           'code_sha256': 'fixture', 'output_dir': str(output),
           'contract_sha256': execution_contract_hash(c),
           'image': 'fixture-image', 'transform_probe_image': 'fixture-image',
           'transform_plans': contract_plans(c)}
    receipts(run)
    return c, files, run


def receipts(run):
    run['artifacts'] = [{'name': p.name, 'sha256': sha(p)}
                        for p in Path(run['output_dir']).glob('*.jsonl')]


@pytest.mark.parametrize('mode', ['sample', 'full'])
def test_host_replay_checks_all_rows_but_cannot_grant_lookup_admission(tmp_path, mode):
    c, files, run = candidate(tmp_path, mode)
    with pytest.raises(NeedsInput) as error:
        validate_candidate(run, c, files, 'fixture', tmp_path)
    assert error.value.details['lookup_replay'] == {
        'row_equality_verified': True, 'mode': mode, 'fact_rows': {'crash': 2},
        'parent_rows': {'codes': 2}, 'admission': False}
    replay = json.loads((tmp_path / 'trusted-lookup-replay-lookup-test.json').read_text())
    assert replay['candidate_counts'] == {'crash': 2, 'unit': 0, 'casualty': 0, 'observation': 0}
    assert replay['lookups'][0]['metrics']['matched'] == 2
    assert replay['admission'] is False


@pytest.mark.parametrize('fault', ['count', 'coordinates', 'raw', 'parent_hash', 'parent_locator',
                                  'match_status', 'canonical_id', 'missing_row', 'duplicate_row', 'extra_row'])
def test_forged_output_is_rejected_before_semantic_gate(tmp_path, fault):
    c, files, run = candidate(tmp_path)
    path = Path(run['output_dir']) / 'crashes.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    row = rows[0]
    if fault == 'count': row['fatalities'] = 999
    if fault == 'coordinates': row['coordinates'] = [149.9, -35.2]
    if fault == 'raw': row['extensions']['Type'] = 'B'
    if fault == 'parent_hash': row['lookup_lineage']['code']['parent']['file_sha256'] = '0' * 64
    if fault == 'parent_locator': row['lookup_lineage']['code']['parent']['row_locator'] = 'csv:2'
    if fault == 'match_status': row['lookup_lineage']['code']['status'] = 'unmatched'
    if fault == 'canonical_id': row['canonical_id'] = '0' * 64
    if fault == 'missing_row': rows.pop()
    if fault == 'duplicate_row': rows.append(copy.deepcopy(row))
    if fault == 'extra_row': rows.append({**row, 'row_locator': 'csv:3'})
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    receipts(run)  # Simulate malicious adapter output, not post-execution file corruption.
    with pytest.raises(ValidationFailure):
        validate_candidate(run, c, files, 'fixture', tmp_path)
    assert not list(tmp_path.glob('trusted-lookup-replay-*.json'))


def test_parent_changes_invalidate_run_even_when_fact_file_is_unchanged(tmp_path):
    c, files, run = candidate(tmp_path)
    path = Path(files[1]['path'])
    path.write_text(path.read_text().replace('A,F,2', 'A,F,9'))
    with pytest.raises(ValidationFailure):
        validate_candidate(run, c, files, 'fixture', tmp_path)


def test_shared_parent_is_counted_once_and_each_binding_conserves_children(tmp_path):
    def configure(c, files):
        r = c['resources'][0]
        r['lookups'].append({**r['lookups'][0], 'name': 'other'})
        r['mapping']['fatalities']['field']['lookup'] = 'other'
    c, files, run = candidate(tmp_path, configure=configure)
    with pytest.raises(NeedsInput) as error:
        validate_candidate(run, c, files, 'fixture', tmp_path)
    assert error.value.details['lookup_replay']['parent_rows'] == {'codes': 2}
    replay = json.loads((tmp_path / 'trusted-lookup-replay-lookup-test.json').read_text())
    assert len(replay['lookups']) == 2
    assert all(item['metrics']['requests'] == 2 for item in replay['lookups'])


def test_compile_only_does_not_open_parent_index_or_issue_success_receipt(tmp_path):
    c, files = bundle(tmp_path)
    work = tmp_path / 'never-created'
    compiled = LookupProjection(c, files, work, compile_only=True)
    try:
        assert not work.exists() and not compiled.indexes
        assert compiled.declarations[0][2]['role'] == 'codes'
        with pytest.raises(ValidationFailure): compiled.project('crash', 'csv:1', {})
        with pytest.raises(ValidationFailure): compiled.receipts()
    finally:
        compiled.close()


@pytest.mark.parametrize('fault', ['unassigned', 'same_physical_table', 'missing_child_key', 'fact_disguise'])
def test_inventory_does_not_hide_rows_behind_lookup_declarations(tmp_path, fault):
    c, files = bundle(tmp_path)
    if fault == 'unassigned':
        files.append(admitted(tmp_path, 'extra.csv', 'ID,Value\n3,X\n'))
    if fault == 'same_physical_table':
        other = {**files[1], 'id': 'second-upload'}
        files.append(other)
        c['lookup_tables'].append({**c['lookup_tables'][0], 'role': 'other', 'file_id': other['id']})
        c['resources'][0]['lookups'].append({**c['resources'][0]['lookups'][0], 'name': 'other', 'parent': 'other'})
        c['resources'][0]['mapping']['fatalities']['field']['lookup'] = 'other'
    if fault in {'missing_child_key', 'fact_disguise'}:
        c['resources'][0]['lookups'][0]['fields'] = ['NotPresent']
        if fault == 'fact_disguise': c['resources'][0]['purpose'] = 'lookup'
    with pytest.raises(ValidationFailure): validate_contract(c, files)


def recipe_fixture(tmp_path, monkeypatch, configure=None):
    c, files = bundle(tmp_path)
    if configure:
        configure(c, files)
    normalized = copy.deepcopy(c)
    for r in input_resources(normalized):
        r.pop('file_id', None)
        for part in r.get('partitions', []): part.pop('file_id', None)
    admission = {'status': 'admitted', 'source_contract_sha256': execution_contract_hash(c), 'image': 'fixture-image'}
    record = {'contract': normalized, 'code_sha256': hashlib.sha256(reuse.ADAPTER.encode()).hexdigest(),
              'verification': {'admission': admission}}
    # Mock only the authority boundary to exercise serialization/rebinding.
    # No registry admission, model execution or publication is performed.
    monkeypatch.setattr(reuse, 'registered', lambda _: record)
    session = SimpleNamespace(validated={'admission': admission, 'source_contract': c},
                              registered={'adapter_version_id': 'fixture'}, code=reuse.ADAPTER,
                              files=files, documents={})
    cache = reuse.ReuseCache(tmp_path / 'cache', 'lookup-test')
    cache.remember(session)
    return cache, c, files, record


def test_recipe_rebinds_fact_and_parent_ids_and_semantic_identity_is_stable(tmp_path, monkeypatch):
    cache, c, files, _ = recipe_fixture(tmp_path, monkeypatch)
    renamed = [{**f, 'id': 'new-' + f['id'], 'name': 'new-' + f['name']} for f in files]
    hit, decision = cache.match(renamed)
    assert decision['route'] == 'verified_recipe_requires_fresh_QA'
    assert [r['file_id'] for r in input_resources(hit['contract'])] == [f['id'] for f in renamed]
    assert semantic_contract(c) == semantic_contract(hit['contract'])


@pytest.mark.parametrize('fault', ['missing_parent', 'changed_parent', 'registry_parent_change'])
def test_recipe_cannot_reuse_only_child_bytes(tmp_path, monkeypatch, fault):
    cache, c, files, record = recipe_fixture(tmp_path, monkeypatch)
    if fault == 'missing_parent': files.pop()
    if fault == 'changed_parent':
        path = Path(files[1]['path'])
        path.write_text(path.read_text().replace('A,F,2', 'A,F,9'))
        files[1].update(sha256=sha(path), size=path.stat().st_size)
    if fault == 'registry_parent_change':
        record['contract']['lookup_tables'][0]['key'] = ['Class']
        with pytest.raises(ValueError, match='immutable registered contract'): cache.match(files)
    else:
        assert cache.match(files)[0] is None


@pytest.mark.parametrize('fault', ['parent_key', 'child_fields', 'missing_policy', 'selection'])
def test_retained_history_rejects_lookup_identity_or_semantics_drift(tmp_path, fault):
    old, _ = bundle(tmp_path)
    new = copy.deepcopy(old)
    if fault == 'parent_key': new['lookup_tables'][0]['key'] = ['Class']
    if fault == 'child_fields': new['resources'][0]['lookups'][0]['fields'] = ['Other']
    if fault == 'missing_policy': new['resources'][0]['lookups'][0]['on_missing'] = 'preserve_unknown'
    if fault == 'selection': new['resources'][0]['lookups'][0]['select'].append('Other')
    with pytest.raises(NeedsInput): require_compatible_update(old, new, 'incremental')


def test_upload_identity_changes_do_not_change_lookup_update_semantics(tmp_path):
    old, _ = bundle(tmp_path)
    new = copy.deepcopy(old)
    for r in input_resources(new): r['file_id'] = 'new-' + r['file_id']
    require_compatible_update(old, new, 'incremental')


def split_parent(c, files):
    path = Path(files[1]['path'])
    path.write_text('Code,Class,Deaths,X,Y\nA,F,2,149.1,-35.2\n')
    files[1].update(sha256=sha(path), size=path.stat().st_size)
    files.append(admitted(path.parent, 'codes-2.csv', 'Code,Class,Deaths,X,Y\nB,U,0,149.2,-35.3\n'))
    c['lookup_tables'][0]['partitions'] = [{'file_id': f['id'], 'table': {}} for f in files[1:]]


def test_parent_partitions_are_rebound_and_all_required_for_reuse(tmp_path, monkeypatch):
    cache, c, files, _ = recipe_fixture(tmp_path, monkeypatch, split_parent)
    renamed = [{**f, 'id': 'new-' + f['id']} for f in files]
    hit, _ = cache.match(renamed)
    parent = hit['contract']['lookup_tables'][0]
    assert [p['file_id'] for p in parent['partitions']] == [f['id'] for f in renamed[1:]]
    assert parent['file_id'] == renamed[1]['id']
    assert semantic_contract(c) == semantic_contract(hit['contract'])
    assert cache.match(renamed[:-1])[0] is None


def test_host_replay_preserves_lookup_parent_partition_lineage(tmp_path):
    c, files, run = candidate(tmp_path, 'full', split_parent)
    with pytest.raises(NeedsInput) as error:
        validate_candidate(run, c, files, 'fixture', tmp_path)
    assert error.value.details['lookup_replay']['parent_rows'] == {'codes': 2}
    rows = [json.loads(line) for line in (Path(run['output_dir']) / 'crashes.jsonl').read_text().splitlines()]
    assert [r['lookup_lineage']['code']['parent']['file_sha256'] for r in rows] == [f['sha256'] for f in files[1:]]


def test_sample_host_replay_scans_unused_parents_beyond_child_sample_bound(tmp_path):
    def configure(c, files):
        path = Path(files[1]['path'])
        path.write_text(path.read_text() + ''.join(f'unused{i},U,0,149.2,-35.3\n' for i in range(1005)))
        files[1].update(sha256=sha(path), size=path.stat().st_size)
    c, files, run = candidate(tmp_path, configure=configure)
    with pytest.raises(NeedsInput) as error:
        validate_candidate(run, c, files, 'fixture', tmp_path)
    assert error.value.details['lookup_replay']['parent_rows'] == {'codes': 1007}
    replay = json.loads((tmp_path / 'trusted-lookup-replay-lookup-test.json').read_text())
    assert replay['lookups'][0]['metrics']['unused_parent_keys'] == 1005


def test_registry_serializes_parent_bindings_without_ephemeral_ids(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from arsia_pipeline import registry, source_identity
    c, files = bundle(tmp_path)
    split_parent(c, files)
    queries = []
    class Connection:
        def transaction(self): return nullcontext()
        def execute(self, sql, args=None): queries.append((sql, args))
    monkeypatch.setattr(registry, 'ROOT', tmp_path / 'private-registry')
    monkeypatch.setattr(registry.store, 'connect', lambda: nullcontext(Connection()))
    monkeypatch.setattr(source_identity, 'canonical_source_identity', lambda *_: {})
    monkeypatch.setattr(source_identity, 'bind_identity', lambda *_: None)
    monkeypatch.setattr(source_identity, 'backfill_identities', lambda *_: None)
    def register_fixture(contract):
        result = {'source_id': c['source']['source_id'], 'qa': [], 'fingerprint': 'fixture', 'admission': {
            'status': 'admitted', 'policy_version': 'synthetic-unit-test',
            'adapter_sha256': hashlib.sha256(reuse.ADAPTER.encode()).hexdigest(),
            'source_contract_sha256': execution_contract_hash(contract)}}
        return registry.register(reuse.ADAPTER, contract, result)
    # Explicitly synthetic admission/connection: tests serialization, not authority.
    first = register_fixture(c)
    normalized = next(args[2].obj for sql, args in queries if sql.startswith('INSERT INTO source_versions'))
    assert all('file_id' not in r for r in input_resources(normalized))
    assert all('file_id' not in p for p in normalized['lookup_tables'][0]['partitions'])
    signature = next(args[6].obj for sql, args in queries if sql.startswith('INSERT INTO adapter_versions'))
    assert signature[0]['lookup_tables'] == normalized['lookup_tables']
    renamed = copy.deepcopy(c)
    for r in input_resources(renamed):
        r['file_id'] = 'new-' + r['file_id']
        for part in r.get('partitions', []): part['file_id'] = 'new-' + part['file_id']
    assert register_fixture(renamed) == first
    renamed['lookup_tables'][0]['key'] = ['Class']
    assert register_fixture(renamed)['source_version_id'] != first['source_version_id']
