"""Real DB policy transitions. Synthetic host admissions are explicit test doubles.

Manual candidates below use the real deterministic parser. Frozen candidates
isolate the old loader protocol; real native/source acceptance is a separate run.
"""
import copy
import json
from pathlib import Path

import pytest

from test_backend import isolated_database, client, queued, claim_specific
from test_autonomous_backend import candidate, published, row
from arsia_pipeline import worker, store, registry
from arsia_pipeline.processing import process_bundle
from arsia_pipeline.publication_policy import seal_deterministic
from arsia_pipeline.errors import NeedsInput, ValidationFailure


def manual(client, source):
    ident = client.post('/jobs', json={'label': 'Manual parser policy test'}).json()['id']
    client.put(f'/jobs/{ident}/files', params={'filename': 'events.csv'}, content=f'ID,YEAR,SEVERITY,NOTE\n001,2024,Injury,{source}\n'.encode()).raise_for_status()
    client.post(f'/jobs/{ident}/submit', json={}).raise_for_status()
    job = claim_specific(ident)
    profile = {'profile_version': 'generic-v1', 'source_id': source, 'jurisdiction': 'SA',
        'source_name': 'Test', 'publisher': 'Test', 'source_evidence': 'Synthetic parser fixture',
        'licence': 'Synthetic', 'confirmed': True, 'analysis': {'year_from': 2024, 'year_to': 2024},
        'resources': [{'role': 'crash', 'filename': 'events.csv', 'key': ['ID']}], 'relations': [],
        'mapping': {'year': 'YEAR', 'severity': 'SEVERITY'},
        'severity': {'Injury': {'code': 'injury', 'label': 'Injury', 'is_fatal_crash': False}}}
    result = process_bundle(job['files'], job['work_dir'], {'profile': profile}, lambda *a, **kw: None, lambda: None)
    return job, result


def frozen(job, source, records, implementation='1'):
    path = job['work_dir']/'fixed.jsonl'
    path.write_text(''.join(json.dumps(v)+'\n' for v in records))
    result = {'source_id': source, 'profile_id': 'frozen-policy-fixture', 'profile_version': '1',
        'canonical_path': str(path), 'fingerprint': registry.digest_json({'rows': records, 'implementation': implementation}),
        'summary': {'crash_count': len(records), 'fatal_crash_count': len(records), 'fatalities': len(records),
            'casualties': len(records)*2, 'canonical_unit_count': 0, 'unit_count': None, 'year_from': 2024, 'year_to': 2024},
        'units': {'status': 'unavailable', 'rows': []}, 'qa': [{'code': 'SYNTHETIC_HOST_QA', 'status': 'pass'}],
        'files': [{k: f[k] for k in ('id', 'name', 'size', 'sha256')} for f in job['files']], 'evidence': {}, 'limitations': ['Synthetic loader policy fixture']}
    seal_deterministic(result, job['files'], native_bundle={'source_id': source, 'profile_id': result['profile_id']})
    return result


def test_manual_cannot_overwrite_registered_official_source(client):
    original, _ = published(client, 'same_source', [row('same_source', 'one')])
    job, result = manual(client, 'same_source')
    with pytest.raises(NeedsInput, match='Manual|manual'):
        worker.publish(job, result, lambda: None)
    with store.connect() as conn:
        assert str(conn.execute('SELECT release_id FROM current_release').fetchone()['release_id']) == original['release_id']
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0


@pytest.mark.parametrize('fault',[None,'leading_zero_lost','wrong_resource'])
def test_real_legacy_key_encoding_transition_preserves_membership_and_blocks_loss(client,fault):
    # Real legacy JSON key shape; synthetic host QA stands in for source research.
    from arsia_pipeline.native_revision import VERSION
    source='native_encoding_'+(fault or 'valid')
    first_job=claim_specific(queued(client)['id'])
    old=row(source,'001');old.pop('canonical_id');old.pop('resource_role')
    old.update(record_id='001',resource_id='frozen-crash-resource')
    old_result=frozen(first_job,source,[old]);worker.publish(first_job,old_result,lambda:None)
    before=store.get_job(first_job['id'])
    next_job=claim_specific(queued(client)['id'])
    receipt={'transition_version':VERSION,'source_id':source,'baseline_profile_id':old_result['profile_id'],'jurisdiction':'QLD',
        'required_resources':[{'role':'crash','grain':'crash','resource_id':'wrong' if fault=='wrong_resource' else 'frozen-crash-resource','file_id':'test'}]}
    key='1' if fault=='leading_zero_lost' else '001'
    revised=candidate(next_job,source,[row(source,key,raw_key=[key]),row(source,'002',raw_key=['002'])],native_transition=receipt)
    if fault:
        with pytest.raises(NeedsInput,match='remove published records'):worker.publish(next_job,revised,lambda:None)
        with store.connect() as conn:assert str(conn.execute('SELECT release_id FROM current_release').fetchone()['release_id'])==before['release_id']
        return
    assert worker.publish(next_job,revised,lambda:None)=='succeeded'
    newest=store.get_job(next_job['id'])
    assert newest['result']['update_membership_verification']['status']=='no_records_removed'
    replay_job=claim_specific(queued(client)['id']);replay=frozen(replay_job,source,[old])
    assert worker.publish(replay_job,replay,lambda:None)=='no_change'
    assert store.get_job(replay_job['id'])['release_id']==newest['release_id']


def test_manual_new_source_is_separate_and_not_official_registry_admission(client, monkeypatch):
    job, result = manual(client, 'manual_research')
    assert worker.publish(job, result, lambda: None) == 'succeeded'
    saved = store.get_job(job['id'])['result']
    assert saved['publication_gate']['admission_level'] == 'manual_reviewed'
    assert saved['publication_gate']['official_registration'] is False
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM source_versions WHERE source_id=%s', ('manual_research',)).fetchone()['n'] == 0
        assert conn.execute('SELECT record_id FROM canonical_crash WHERE batch_id=%s', (store.get_job(job['id'])['batch_id'],)).fetchone()['record_id'] == '["001"]'
    saved_job = store.get_job(job['id'])
    source = next(s for s in client.get('/catalog', params={'release_id': saved_job['release_id']}).json()['sources']
                  if s['source_id'] == 'manual_research')
    assert source['publication_status'] == {
        'admission_level': 'manual_reviewed', 'official_registration': False,
        'scope': 'local_research', 'label': 'Local research: official source identity unverified'}
    query = client.get('/query', params={'release_id': saved_job['release_id'], 'source_id': 'manual_research',
        'from': '2024-01-01', 'to': '2024-12-31'}).json()
    assert query['publication_status'] == source['publication_status']
    assert query['summary'] == {'crash_count': 1, 'fatal_crash_count': 0, 'fatalities': None, 'casualties': None}
    from arsia_pipeline import config
    from tools.acceptance_web import verify
    cfg = config.read_config()
    monkeypatch.setenv('ARSIA_ACCEPTANCE_INSTANCE', cfg['instance_id'])
    verify(Path(cfg['storage_home']), saved_job, {'rows': 1, 'fatal_crashes': 0, 'manualResearch': True})


def test_new_publication_catalog_uses_reconciled_facts_without_rescanning_rows(client):
    from arsia_pipeline import query
    job,result=manual(client,'catalog_materialized')
    worker.publish(job,result,lambda:None)
    saved=store.get_job(job['id'])
    class NoDetailScan:
        def execute(self,*args):raise AssertionError('Catalog must not scan canonical details for new publications')
    with store.connect() as conn:
        batch=conn.execute('SELECT * FROM batches WHERE id=%s',(saved['batch_id'],)).fetchone()
    for _ in range(50):
        metadata=query.metadata(result['source_id'],saved['batch_id'],batch,NoDetailScan())
        assert metadata['capabilities']['monthly'] is False
    assert batch['result']['query_facts']['row_count']==1


@pytest.mark.parametrize('changed_implementation', [False, True])
def test_old_deterministic_entry_cannot_roll_back_new_admitted_version(client, changed_implementation):
    source = 'fixed_transition_'+str(int(changed_implementation))
    records = [row(source, 'one')]
    first_job = claim_specific(queued(client)['id'])
    first = frozen(first_job, source, records)
    assert worker.publish(first_job, first, lambda: None) == 'succeeded'
    next_job = claim_specific(queued(client)['id'])
    revised = candidate(next_job, source, records+[row(source, 'two')], version='new')
    assert worker.publish(next_job, revised, lambda: None) == 'succeeded'
    newest = store.get_job(next_job['id'])
    old_job = claim_specific(queued(client)['id'])
    replay = frozen(old_job, source, records, implementation='2' if changed_implementation else '1')
    assert worker.publish(old_job, replay, lambda: None) == 'no_change'
    kept = store.get_job(old_job['id'])
    assert kept['release_id'] == newest['release_id'] and kept['batch_id'] == newest['batch_id']
    assert kept['result']['summary']['crash_count'] == 2
    assert kept['result']['publication_evidence']['reason'] == 'historical_input_replay'


@pytest.mark.parametrize('fault', ['qa', 'output', 'input', 'policy', 'finished_attempt'])
def test_current_deterministic_gate_rejects_stale_or_mutated_candidate(client, fault):
    job, result = manual(client, 'invalid_'+fault)
    if fault == 'qa': result['qa'][0]['status'] = 'block'
    elif fault == 'output': Path(result['canonical_path']).write_text('{}\n')
    elif fault == 'input': Path(job['files'][0]['path']).write_bytes(b'changed')
    elif fault == 'policy': result['publication_gate']['implementation']['worker.py'] = '0'*64
    else:
        with store.connect() as conn:
            conn.execute("UPDATE attempts SET status='failed',finished_at=now() WHERE id=%s", (job['attempt_id'],))
    with pytest.raises(ValidationFailure): worker.publish(job, result, lambda: None)
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0


def test_observed_span_query_does_not_invent_zero_months(client):
    from arsia_pipeline import query
    source='observed_span_only'
    job,_=published(client,source,[row(source,'jan'),row(source,'dec',month=12)])
    value=query.query(source,job['release_id'],'2024-02-01','2024-02-29')
    assert value['coverage']['complete'] is False
    assert value['summary']=={k:None for k in query.METRICS}
    assert value['monthly']==[]
    observed=query.query(source,job['release_id'],'2024-01-01','2024-12-31')
    assert observed['summary']['crash_count']==2
    assert [m['month'] for m in observed['monthly']]==[1,12]
    assert observed['coverage']['complete'] is False


def test_complete_dataset_snapshot_emits_zero_only_inside_proven_intervals(client):
    # A host-policy fixture stands in for the reviewed fixed-native scope proof;
    # the database/query path and expected calendar totals are independent.
    from arsia_pipeline import query
    from arsia_pipeline.coverage_policy import VERSION
    job=claim_specific(queued(client)['id']); source='complete_calendar'
    result=frozen(job,source,[row(source,'jan')])
    result['temporal_coverage']={'version':VERSION,'complete_intervals':[{'from':'2024-01-01','to':'2024-02-29'}]}
    result['coverage']={'from':'2024-01-01','to':'2024-12-31'}
    result['capabilities']={'monthly':True}
    seal_deterministic(result,job['files'],native_bundle={'source_id':source,'profile_id':result['profile_id']})
    worker.publish(job,result,lambda:None);saved=store.get_job(job['id'])
    feb=query.query(source,saved['release_id'],'2024-02-01','2024-02-29')
    assert feb['coverage']['complete'] is True
    assert feb['monthly']==[{'year':2024,'month':2,'crash_count':0,'fatal_crash_count':0,'fatalities':0,'casualties':0}]
    march=query.query(source,saved['release_id'],'2024-03-01','2024-03-31')
    assert march['coverage']['complete'] is False and march['summary']['crash_count'] is None
