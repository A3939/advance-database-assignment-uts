"""Real inventory/transport boundaries; fixtures do not assert official identity."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from arsia_pipeline import task_authority as scope
from arsia_pipeline.errors import BudgetExhausted, NeedsInput, ValidationFailure
from arsia_pipeline.intake_tools import IntakeTools
from arsia_pipeline.trusted_qa import validate_contract
from test_canonical_v2 import envelope
import test_public_sources as public_fixtures


@pytest.mark.parametrize('evidence_first', [True, False])
def test_same_zip_cache_keeps_each_parents_authority(tmp_path, evidence_first):
    contract, original, _ = envelope(tmp_path)
    path = tmp_path / 'comparison.zip'
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('crashes.csv', 'ID,DATE,SEVERITY\nother,2020-01-01,Injury\n')
    base = {'name': path.name, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'size': path.stat().st_size}
    fetched = {**base, 'id': 'fetched', 'role': 'public_evidence'}
    uploaded = {**base, 'id': 'uploaded'}
    tools = IntakeTools([original], tmp_path / 'work')
    for parent in ([fetched, uploaded] if evidence_first else [uploaded, fetched]):
        tools.register_files([parent]); tools.inspect_bundle()
    children = {f['archive_file_id']: f for f in tools.files if f.get('archive_file_id')}
    assert children['fetched']['role'] == 'public_evidence'
    assert 'role' not in children['uploaded']
    assert children['fetched']['path'] == children['uploaded']['path']
    assert children['fetched']['id'] != children['uploaded']['id']
    # A downloaded reference is optional evidence; actual uploaded rows cannot
    # be hidden by a same-hash reference or by changing archive packaging.
    validate_contract(contract, [original, fetched, children['fetched']])
    with pytest.raises(ValidationFailure, match='not assigned a grain'):
        validate_contract(contract, tools.files)


def test_unknown_review_clamps_bytes_timeout_and_survives_strategy_change(tmp_path, monkeypatch):
    session = SimpleNamespace(runtime_state={})
    assert scope.request_limits(session, 512*1024**2, 300) == (2*1024**2, 15)
    scope.charge_download(session, 3*1024**2)
    restored = SimpleNamespace(runtime_state=json.loads(json.dumps(session.runtime_state)))
    scope.state(restored)['status'] = 'scoped_for_investigation'
    scope.charge_download(restored, 1024)
    assert scope.resource_usage(restored)['download_bytes'] == 3*1024**2 + 1024
    assert scope.resource_usage(restored)['metadata_download_bytes'] == 3*1024**2


def test_download_overrun_charged_and_discovery_does_not_swallow_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(scope, 'METADATA_BYTES', 10)
    monkeypatch.setattr(scope, 'DOWNLOAD_BYTES', 100)
    session = SimpleNamespace(runtime_state={})
    fixture = public_fixtures.PublicTests(); fixture.setUp()
    try:
        tool = fixture.tool([public_fixtures.Response(b'1234', headers={'Content-Length': None}) for _ in range(3)])
        tool.request_limits = lambda size, seconds: scope.request_limits(session, size, seconds)
        tool.charge_bytes = lambda count: scope.charge_download(session, count)
        for _ in range(2): tool.fetch_public_source('https://source.gov.au/doc')
        with pytest.raises(BudgetExhausted): tool.fetch_public_source('https://source.gov.au/doc')
        assert scope.resource_usage(session)['download_bytes'] == 11
        # Dedupe does not refund network cost, and no fourth connection starts.
        assert len(list((tool.root/'sha256').iterdir())) == 1
        with pytest.raises(BudgetExhausted): tool.discover_source_docs('road crash')
        assert len(fixture.connections) == 3
    finally: fixture.tearDown()


def test_storage_includes_previous_attempt_and_ignores_symlink_targets(tmp_path, monkeypatch):
    monkeypatch.setattr(scope, 'TASK_STORAGE_BYTES', 32)
    work = tmp_path/'job'/'new'; work.mkdir(parents=True)
    previous = work.parent/'previous'; previous.mkdir()
    session = SimpleNamespace(runtime_state={}, job={'work_dir':work})
    outside = tmp_path/'outside'; outside.write_bytes(b'x'*100)
    (work/'link').symlink_to(outside)
    scope.check_storage(session, force=True)
    (previous/'retained').write_bytes(b'x'*33)
    with pytest.raises(BudgetExhausted, match='storage'):
        scope.check_storage(session, force=True)


def test_adapter_classified_failure_can_request_untrusted_engineering_review(tmp_path):
    from arsia_pipeline import repair_context
    session = SimpleNamespace(files=[], runtime_state={}, job={'id':'job','attempt_id':'attempt'},
        work_dir=tmp_path, contract={}, code='', usage={'tool_calls':10}, active_wall_seconds=lambda:5)
    current = repair_context.record(session, ValidationFailure('Inventory omitted a comparison origin'), 'set_source_contract')
    assert current['route'] == 'data_investigation'
    with pytest.raises(NeedsInput) as error:
        repair_context.engineering_handoff(session, {'blocker_id':current['blocker_id'],
            'proposal':'Reproduce in an independent source tree; test both uploaded and fetched archive parents.'})
    assert error.value.code == 'engineering_repair_required'
    packet = json.loads(next(tmp_path.glob('engineering-*.json')).read_text())
    assert packet['trusted'] is False and packet['automatic_load_allowed'] is False
    assert packet['budget_consumed'] == {'tool_calls':10}


@pytest.mark.parametrize('code', ['STORAGE_SYMLINK','STORAGE_OWNER','STORAGE_PATH','STORAGE_BUDGET'])
def test_storage_integrity_and_budget_remain_stops(code):
    from arsia_pipeline.storage_lifecycle import StorageError
    from arsia_pipeline.capability_preflight import classified_blockers
    from arsia_pipeline.repair_context import route
    exc = StorageError(code, 'Controlled boundary counterexample')
    assert route(exc, classified_blockers(exc)) == 'stop'
