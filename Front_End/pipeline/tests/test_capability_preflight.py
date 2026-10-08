import copy
import hashlib
import json
import threading

import pytest

from arsia_pipeline.capability_preflight import preflight_contract, inspect_capabilities, requires_system_change, blocker
from arsia_pipeline.errors import NeedsInput
from test_contract_patch import offline_session


def feature_session(tmp_path, geometry, *, arcgis=False):
    session = offline_session(tmp_path)
    data = {'geometryType': 'esriGeometryPoint', 'features': [{'attributes': {'ID': 'a', 'DATE': '2024-01-01'}, 'geometry': geometry}], 'spatialReference': {'wkid': 4326}} if arcgis else {
        'type': 'FeatureCollection', 'features': [{'type': 'Feature', 'properties': {'ID': 'a', 'DATE': '2024-01-01'}, 'geometry': geometry}]}
    path = tmp_path / 'events.json'; path.write_text(json.dumps(data))
    session.files = [{'id': 'input', 'name': path.name, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}]
    session.contract['resources'][0]['table'] = {}
    session.contract['resources'][0]['mapping']['geography'] = {'x_field': '__geometry_x', 'y_field': '__geometry_y', 'crs': 'EPSG:4326'}
    return session


def test_nonpoint_is_a_system_blocker_before_missing_evidence(tmp_path):
    session = feature_session(tmp_path, {'type': 'LineString', 'coordinates': [[149,-35],[150,-36]]})
    result = preflight_contract(session.contract, session.files, tmp_path)
    assert result['blockers'][0]['code'] == 'NONPOINT_GEOMETRY_UNSUPPORTED'
    assert requires_system_change(result) and result['admission'] is False
    with pytest.raises(NeedsInput) as error:
        session.execute_tool('set_source_contract', {'contract': copy.deepcopy(session.contract)})
    assert error.value.questions == [] and requires_system_change(error.value.details)


def test_uploaded_geometry_crs_cannot_be_overridden_by_contract(tmp_path):
    session = feature_session(tmp_path, {'x': 149, 'y': -35, 'spatialReference': {'wkid': 4283}}, arcgis=True)
    result = preflight_contract(session.contract, session.files, tmp_path)
    assert result['blockers'][0]['code'] == 'GEOMETRY_CRS_CONFLICT'
    assert result['blockers'][0]['kind'] == 'evidence_conflict'


def test_unsupported_inner_crs_is_system_work_not_a_missing_dictionary(tmp_path):
    session = feature_session(tmp_path, {'type': 'Point', 'coordinates': [149, -35],
        'crs': {'type': 'name', 'properties': {'name': 'EPSG:4283'}}})
    result = preflight_contract(session.contract, session.files, tmp_path)
    assert requires_system_change(result)
    assert result['blockers'][0]['code'] == 'FEATURE_CRS_UNSUPPORTED'
    assert result['blockers'][0]['responsible_party'] == 'system'


def test_inspection_does_not_lose_reader_system_blocker(tmp_path):
    from arsia_pipeline.intake_tools import IntakeTools
    path = tmp_path / 'positional.json'; path.write_text('[["a", "2024-01-01"]]')
    file = {'id': 'source', 'name': path.name, 'path': str(path), 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    inventory = IntakeTools([file], tmp_path / 'tools').inspect_bundle()
    resource, = inspect_capabilities(inventory['resources'])['resources']
    assert resource['tables'] == [] and requires_system_change(resource)
    assert resource['blockers'][0]['code'] == 'ARRAY_RECORDS_UNSUPPORTED'


def test_missing_evidence_prevents_any_sample_executor_launch(tmp_path, monkeypatch):
    from arsia_pipeline import isolated_executor
    session = offline_session(tmp_path)
    monkeypatch.setattr(isolated_executor, 'run_python', lambda *a, **k: pytest.fail('Executor must not launch before preflight'))
    with pytest.raises(NeedsInput) as error:
        session.execute_tool('run_adapter', {'mode': 'sample'})
    assert error.value.details['blockers'][0]['kind'] == 'evidence_missing'
    assert session.usage['model_calls'] == 0


def test_real_source_proof_preflight_and_compact_result(tmp_path, monkeypatch):
    from arsia_pipeline import config
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    session = offline_session(tmp_path)
    from test_limited_geography import source_fixture
    contract, files = source_fixture(tmp_path)
    session.contract, session.files = contract, files
    session.documents = {d['document_id']: d for d in contract.pop('documents')}
    before = copy.deepcopy(session.contract)
    result = session.execute_tool('preflight_contract', {})
    assert result['ok'] and result['admission'] is False and result['field_binding_count'] == 2
    assert 'source_contract' not in result and 'proof' not in result
    assert session.contract == before and session.usage['model_calls'] == 0


def test_inventory_reports_nonpoint_without_claiming_admission():
    result = inspect_capabilities([{'file_id': 'upload', 'format': 'json', 'tables': [{'table_id': 'default', 'observed_geometry_types': ['Polygon']}]}])
    assert requires_system_change(result['resources'][0]['tables'][0])
    assert result['admission'] is False


def test_mapped_field_missing_from_upload_fails_before_execution(tmp_path):
    session = offline_session(tmp_path)
    session.contract['resources'][0]['mapping']['date']['field'] = 'other_date'
    result = preflight_contract(session.contract, session.files, tmp_path)
    assert result['blockers'][0]['code'] == 'MAPPED_FIELD_ABSENT'
    assert result['blockers'][0]['details']['fields'] == ['other_date']


def test_codex_bridge_stops_on_system_blocker_without_new_model_calls(tmp_path):
    from arsia_pipeline.codex_bridge import TaskBridge
    from types import SimpleNamespace
    system_issue = blocker('NONPOINT_GEOMETRY_UNSUPPORTED', 'unsupported_capability', 'Point maps do not represent lines.')
    def execute(*args): raise NeedsInput('Requires system update', [], {'blockers': [system_issue]})
    recorded = []
    session = SimpleNamespace(check_budget=lambda: None, ready=None, usage={'tool_calls': 0, 'model_calls': 0},
        step=lambda *a: 1, active_tool={}, persist=lambda *a: None, progress=lambda *a, **k: None,
        execute_tool=execute, finish_step=lambda *args: recorded.append(args), contract={}, code='', errors={})
    bridge = object.__new__(TaskBridge)
    bridge.lock = threading.RLock(); bridge.closed = threading.Event(); bridge.terminal = None
    bridge.session = session; bridge.workspace = tmp_path; bridge.snapshot = lambda: None
    (tmp_path / 'evidence').mkdir()
    result, error = bridge.tool('run_adapter', {'mode': 'sample'})
    assert error and result['output']['status'] == 'paused' and result['output']['questions'] == []
    assert isinstance(bridge.terminal, NeedsInput)
    with pytest.raises(ValueError, match='no longer'):
        bridge.tool('inspect_capabilities', {})
    assert session.usage['model_calls'] == 0 and session.usage['tool_calls'] == 1
