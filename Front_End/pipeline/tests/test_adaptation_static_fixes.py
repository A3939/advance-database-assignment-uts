"""Static-review regression source, written but NOT RUN in this delivery.

No tests in this file constitute evidence of runtime correctness until the user
supplies data and authorizes verification. Doubles here isolate the real wrapping
and terminal paths, not a duplicate implementation of their decision rules.
"""
import copy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

from arsia_pipeline import agent, capability_preflight, isolated_executor, trusted_qa
from arsia_pipeline.adapter_reuse import rebind_version_evidence, VersionCandidateDeclined
from arsia_pipeline.capability_preflight import execution_blockers, requires_system_change
from arsia_pipeline.errors import NeedsInput, ImportCancelled
from arsia_pipeline.source_knowledge import reuse_metadata_compatibility


@pytest.mark.parametrize('mode', ['sample', 'full'])
def test_real_run_dispatch_keeps_image_unavailable_and_stops(tmp_path, monkeypatch, mode):
    s = agent.AgentSession.__new__(agent.AgentSession)
    s.adaptation_v1 = True
    s.contract = {'contract_version': 'canonical-v2'}
    s.documents, s.files, s.runs, s.runtime_state = {}, [], {}, {}
    s.code = 'def adapt(ctx): pass'
    s.native_context = None
    s.enforce_native_boundary = lambda: None
    s.work_dir = tmp_path/'agent'
    s.job = {'work_dir': tmp_path/'job', 'id': 'job', 'attempt_id': 'attempt'}
    s.cancel = lambda: None
    s.usage = {'compute_seconds': 0}
    s.validated, s.registered = object(), object()
    s.sample_gate = {'code_sha256': hashlib.sha256(s.code.encode()).hexdigest(),
                     'contract_sha256': agent.registry.execution_contract_hash({**s.contract, 'documents': []}),
                     'image': 'sha256:previous-image'}
    saved = []
    s.persist = lambda status='investigating': saved.append((status, copy.deepcopy(s.runtime_state)))
    monkeypatch.setattr(trusted_qa, 'validate_contract', lambda *a, **kw: None)
    monkeypatch.setattr(capability_preflight, 'preflight_contract', lambda *a, **kw: {'ok': True})
    monkeypatch.setattr(agent, 'read_config', lambda: {'instance_id': 'test', 'data_root': str(tmp_path)})
    monkeypatch.setattr(isolated_executor, 'run_python', lambda *a, **kw: {
        'run_id': 'run', 'status': 'unavailable', 'error': {
            'type': 'ImageUnavailable', 'message': 'Dedicated image missing'}})
    with pytest.raises(NeedsInput) as error:
        s.execute_tool('run_adapter', {'mode': mode})
    row = error.value.details['blockers'][0]
    assert row['code'] == 'EXECUTOR_IMAGE_UNAVAILABLE'
    assert row['kind'] == 'environment_dependency'
    assert row['responsible_party'] == 'system' and row['resumable_when']
    assert row['details']['executor_error']['type'] == 'ImageUnavailable'
    assert saved[-1][0] == 'needs_input'
    assert saved[-1][1]['adaptation_blocker']['run_id'] == 'run'
    assert s.runs['run']['status'] == 'unavailable'
    assert s.validated is None and s.registered is None


@pytest.mark.parametrize('kind', ['ImportError','ModuleNotFoundError','FileNotFoundError','SyntaxError'])
def test_generated_exceptions_remain_adapter_repairs(kind):
    rows = execution_blockers({'status': 'failed', 'run_id': 'run',
                               'error': {'type': kind, 'origin': 'adapter', 'message': 'Bounded failure'}}, operation='run_python')
    assert rows[0]['kind'] == 'adapter_revision'
    assert not requires_system_change({'blockers': rows})


def test_runner_cannot_forge_environment_authority():
    out = isolated_executor.bounded_report({'status': 'unavailable', 'error': {
        'type': 'ImageUnavailable', 'origin': 'trusted_host', 'kind': 'environment_dependency'}},
        isolated_executor.DEFAULT_LIMITS)
    assert out['status'] == 'failed' and out['error']['origin'] == 'adapter'
    assert out['error']['type'] == 'AdapterError'
    assert execution_blockers(out, operation='run_adapter')[0]['kind'] == 'adapter_revision'


def test_returned_cancellation_is_not_an_adapter_retry():
    with pytest.raises(ImportCancelled):
        execution_blockers({'status': 'cancelled', 'error': {'type': 'Cancelled'}}, operation='run_adapter')


def test_codex_bridge_consumes_system_terminal_and_refuses_next_tool(tmp_path):
    from arsia_pipeline.codex_bridge import TaskBridge
    s = agent.AgentSession.__new__(agent.AgentSession)
    s.adaptation_v1, s.ready = True, None
    s.runtime_state, s.contract, s.code = {}, {}, ''
    s.usage, s.errors = {'tool_calls': 0}, {}
    s.check_budget = lambda **kw: None
    s.step = lambda *a: 1
    s.progress = lambda *a, **kw: None
    saved, finished = [], []
    s.persist = lambda status='investigating': saved.append(status)
    s.finish_step = lambda *args: finished.append(args)
    s._execute_tool = lambda *a: {'run_id': 'run', 'status': 'unavailable',
                                'error': {'type': 'ImageUnavailable', 'origin': 'trusted_host'}}
    # Exercise tool() without starting a bridge server or a model transport.
    bridge = TaskBridge.__new__(TaskBridge)
    bridge.lock, bridge.closed, bridge.terminal = threading.RLock(), threading.Event(), None
    bridge.session, bridge.workspace = s, tmp_path
    (tmp_path / 'evidence').mkdir()
    bridge.snapshot = lambda: None
    _, error = bridge.tool('run_adapter', {'mode': 'sample'})
    assert error and isinstance(bridge.terminal, NeedsInput)
    assert saved[-1] == 'needs_input' and finished[-1][-1] == 'paused'
    assert finished[-1][1]['details']['blockers'][0]['code'] == 'EXECUTOR_IMAGE_UNAVAILABLE'
    with pytest.raises(ValueError, match='no longer'):
        bridge.tool('get_workflow_state', {})
    assert s.usage['tool_calls'] == 1


URL = 'https://data.example.gov.au/api/3/action/package_show?id=crashes'


def metadata():
    return {'success': True, 'result': {'id': 'uuid', 'name': 'crashes',
        'metadata_modified': '2026-10-01T00:00:00', 'tracking_summary': {'total': 10, 'recent': 1},
        'resources': [{'id': 'csv', 'url': 'https://data.example.gov.au/crashes.csv',
                       'fields': [{'name': 'ID', 'type': 'text'}, {'name': 'X', 'crs': 'EPSG:4326'}]}]}}


def raw(value, **kwargs):
    return json.dumps(value, **kwargs).encode()


def test_ckan_cosmetics_keep_both_raw_hashes_and_exact_change_paths():
    old = metadata(); new = copy.deepcopy(old)
    new['result']['metadata_modified'] = '2026-10-02T01:02:03'
    new['result']['tracking_summary']['total'] = 99
    result = reuse_metadata_compatibility(raw(old), raw(new, indent=4, sort_keys=True), URL)
    assert result['compatible'] is True
    assert result['before_raw_sha256'] != result['after_raw_sha256']
    assert {x['path'] for x in result['allowed_changes']} == {
        '/result/metadata_modified', '/result/tracking_summary/total'}
    assert result['admission'] is False


@pytest.mark.parametrize('mutate', [
    lambda d: d['result'].update(revision_id='new'),
    lambda d: d['result'].update(unknown_metadata='new'),
    lambda d: d['result'].update(coverage='2026-2027'),
    lambda d: d['result'].update(id='another-dataset'),
    lambda d: d['result']['resources'][0]['fields'][1].update(crs='EPSG:7855'),
    lambda d: d['result']['resources'][0].update(url='https://data.example.gov.au/other.csv'),
])
def test_semantic_and_unknown_changes_never_auto_compatible(mutate):
    old = metadata(); new = copy.deepcopy(old); mutate(new)
    assert reuse_metadata_compatibility(raw(old), raw(new), URL)['compatible'] is False


def test_non_json_page_and_unreviewed_provider_are_not_normalized():
    assert not reuse_metadata_compatibility(b'<html>old</html>', b'<html>new</html>', URL)['compatible']
    assert not reuse_metadata_compatibility(raw(metadata()), raw(metadata()), 'https://other.gov.au/dataset/crashes')['compatible']


def test_fresh_hash_references_are_reissued_only_for_equal_values():
    from arsia_pipeline.evidence_references import reference
    old = metadata(); new = copy.deepcopy(old)
    new['result']['metadata_modified'] = '2026-10-02T00:00:00'
    before, after = raw(old), raw(new)
    old_doc = {'document_id': 'old', 'sha256': hashlib.sha256(before).hexdigest(), 'url': URL}
    fresh = {'document_id': 'fresh', 'sha256': hashlib.sha256(after).hexdigest(), 'url': URL}
    entry = reference(before, old_doc['sha256'], 'old', {'kind': 'json-pointer', 'pointer': '/result/resources/0/fields/0'})
    c = {'evidence': {'fields': [entry]}}
    rebind_version_evidence(c, old_doc, fresh, before, after)
    assert c['evidence']['fields'][0]['document_id'] == 'fresh'
    assert c['evidence']['fields'][0]['document_sha256'] == fresh['sha256']
    assert c['evidence']['fields'][0]['value_sha256'] == entry['value_sha256']
    with pytest.raises(VersionCandidateDeclined, match='CITATION_REBIND_UNSUPPORTED'):
        rebind_version_evidence({'evidence': {'date': [{'document_id': 'old', 'quote': 'Free text'}]}}, old_doc, fresh, before, after)


def test_semantic_compatibility_does_not_replace_missing_upload_binding(tmp_path, monkeypatch):
    from arsia_pipeline import adapter_reuse as reuse
    payload = b'ID,DATE\n001,2024-01-01\n'
    path = tmp_path/'uploaded.csv'; path.write_bytes(payload)
    file = {'id': 'new', 'name': path.name, 'path': str(path), 'sha256': hashlib.sha256(payload).hexdigest(), 'size': len(payload)}
    shape = {'format': 'csv', 'table_id': 'default', 'fields': ['DATE','ID'], 'encoding': 'utf-8', 'delimiter': ','}
    source_url = 'https://data.example.gov.au/crashes.csv'
    doc = {'document_id': 'doc', 'url': URL, 'sha256': 'a'*64}
    record = {'instance': 'test', 'format': 'admitted-recipe-v1', 'documents': [doc],
              'contract': {'source': {}, 'resources': [{'role': 'crash', 'file_id': 'old'}]},
              'version_candidate': {'eligible': True, 'resources': [{'role': 'crash', 'source_url': source_url, 'shape': shape}]}}
    folder = tmp_path/'cache'; folder.mkdir(); (folder/'recipe').write_text('placeholder')
    cache = SimpleNamespace(instance='test', store=SimpleNamespace(root=folder, get=lambda _: json.dumps(record)), index=SimpleNamespace(shortlist=lambda **kwargs: (['recipe'],False)))
    s = SimpleNamespace(files=[file], cancel=lambda: None, runtime_state={}, persist=lambda *a: None)
    monkeypatch.setattr(reuse, 'verified_version_record', lambda *a: None)
    monkeypatch.setattr(reuse, 'csv_shape', lambda *a: (shape, {}))
    monkeypatch.setattr(reuse, 'version_signature', lambda *a: 'compatible-candidate')
    monkeypatch.setattr(reuse, 'refresh_version_document', lambda *a: (doc, {'compatible': True, 'rule': 'fixture-only'}))
    monkeypatch.setattr(reuse, 'controlled', lambda *a: {'status': 'fetched', 'final_url': source_url, 'sha256': '0'*64, 'size': len(payload)})
    monkeypatch.setattr(reuse, 'measured_coverage', lambda *a: pytest.fail('An unbound upload must not advance to coverage or QA'))
    candidate, decision = reuse.prepare_version_candidate(cache, s)
    assert candidate is None
    assert decision['differences'][0]['code'] == 'VERSION_OFFICIAL_BYTES_UNBOUND'
    assert decision['evidence_refresh'][0]['compatible'] is True


def test_controlled_reuse_preserves_stop_and_cancel_status():
    from arsia_pipeline.adapter_reuse import controlled
    from arsia_pipeline.capability_preflight import blocker
    for exception, expected in [
        (NeedsInput('Missing image', [], {'blockers': [blocker('IMAGE', 'environment_dependency', 'Missing image')]}), 'needs_input'),
        (ImportCancelled('cancelled'), 'cancelled'),
    ]:
        saved = []
        def fail(*a):
            raise exception
        s = SimpleNamespace(check_budget=lambda: None, usage={'tool_calls': 0}, step=lambda *a: 1,
                            execute_tool=fail, finish_step=lambda *a: None, persist=lambda status: saved.append(status))
        with pytest.raises(type(exception)):
            controlled(s, 'run_adapter', {'mode': 'sample'})
        assert saved == [expected] and s.active_tool == {}
