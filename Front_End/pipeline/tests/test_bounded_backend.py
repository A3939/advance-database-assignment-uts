"""Owned PostgreSQL boundary fixtures; no real model or official admission claim."""
import copy
import threading
from types import SimpleNamespace
from pathlib import Path

import pytest
from test_backend import isolated_database, client, queued, claim_specific
from test_autonomous_backend import session_for, candidate, row
from test_codex_integration import bridge_for
from arsia_pipeline import agent, store, worker, query, registry, repair_context, independent_versions
from arsia_pipeline.errors import NeedsInput


@pytest.mark.parametrize('publication', [False, True])
def test_deterministic_needs_input_enters_one_bounded_agent_with_original_blocker(client, monkeypatch, publication):
    from arsia_pipeline import processing, native_revision
    job = claim_specific(queued(client)['id'])
    job['options']['profile'] = {'profile_version':'generic-v1'}
    cfg = worker.read_config()
    monkeypatch.setattr(worker, 'read_config', lambda:{**cfg, 'bounded_repair_v1':True})
    monkeypatch.setattr(native_revision, 'classify_native_route', lambda *a:SimpleNamespace(kind='unknown',context=None))
    original = NeedsInput('Controlled publication authority gap' if publication else 'Controlled missing mapping fact')
    def blocked(*a, **k): raise original
    monkeypatch.setattr(processing, 'process_bundle', (lambda *a:{'profile_id':'controlled'}) if publication else blocked)
    if publication: monkeypatch.setattr(worker, 'publish', blocked)
    calls = []
    def investigate(*a, **kw):
        calls.append(kw['initial_blocker'])
        raise NeedsInput('Controlled Agent retained an unresolved official fact', [], {'fixture':True})
    monkeypatch.setattr(agent, 'agent_process', investigate)
    worker.execute(job, threading.Event())
    assert calls == [(original, 'deterministic_publication' if publication else 'deterministic_intake')]
    saved = store.get_job(job['id'])
    assert saved['status'] == 'needs_input'
    assert saved['error']['routing']['automatic_retry'] is False


@pytest.mark.parametrize('pinned,budget', [(True,False),(False,True)])
def test_deterministic_stop_cannot_spawn_another_agent(client, monkeypatch, pinned, budget):
    from arsia_pipeline import processing, native_revision
    from arsia_pipeline.errors import BudgetExhausted
    job = claim_specific(queued(client)['id']); cfg = worker.read_config()
    monkeypatch.setattr(worker, 'read_config', lambda:{**cfg, 'bounded_repair_v1':True})
    monkeypatch.setattr(native_revision, 'classify_native_route', lambda *a:SimpleNamespace(kind='pinned' if pinned else 'unknown',context=None))
    def stopped(*a, **k): raise BudgetExhausted('fixture limit') if budget else NeedsInput('fixed source boundary')
    monkeypatch.setattr(processing, 'process_bundle', stopped)
    monkeypatch.setattr(agent, 'agent_process', lambda *a,**k:pytest.fail('Stop must not spawn an Agent'))
    worker.execute(job, threading.Event())
    saved = store.get_job(job['id'])
    assert saved['status'] == 'needs_input'
    assert saved['error']['routing']['route'] == ('stop' if budget else 'engineering_review')


def scoped(s):
    s.bounded_repair_v1=True; s.adaptation_v1=True
    s.runtime_state['task_authority']={'status':'scoped_for_investigation','files':{},'review_actions':0}
    s.runtime_state['original_goal']={'objective':'Import road crashes; preserve prior results','target_satisfied':False}
    return s


def test_real_publication_failure_returns_to_same_agent_then_success(client):
    s=scoped(session_for(client)); b=bridge_for(s)
    source='bounded_publication_fixture'
    s.publisher=lambda result: worker.publish(s.job,result,lambda:None)
    try:
        result=candidate(s.job,source,[row(source,'bad')])
        s.validated=result; s.registered={}
        # Require nonempty immutable registration as production does.
        s.registered={k:result[k] for k in ('adapter_version_id','source_version_id','code_sha256')}
        path=Path(result['canonical_path']); original=path.read_bytes();path.write_text('{}\n')
        before=query.catalog()
        out,error=b.tool('publish_candidate',{})
        assert error and not b.terminal and s.ready is None
        assert query.catalog()==before
        assert s.runtime_state['repair']['operation']=='publish_candidate'
        assert s.runtime_state['repair']['binding']['attempt_id']==str(s.job['attempt_id'])
        first=s.usage['tool_calls']
        # Controlled fixture repairs exactly the corrupted candidate bytes.
        path.write_bytes(original)
        out,error=b.tool('publish_candidate',{})
        assert not error and s.usage['tool_calls']==first+1
        assert store.get_job(s.job['id'])['status']=='succeeded'
        assert s.ready['_publication_status']=='succeeded'
        with store.connect() as conn:
            assert conn.execute('SELECT count(*) n FROM batches WHERE job_id=%s',(s.job['id'],)).fetchone()['n']==1
            saved=conn.execute('SELECT checkpoint FROM agent_sessions WHERE id=%s',(s.id,)).fetchone()['checkpoint']
        assert saved['runtime_state']['original_goal']['objective'].startswith('Import road crashes')
    finally:b.stop()


def version_candidate(job, marker, keys):
    # Synthetic loader fixture; version hash is an input namespace, not evidence.
    url='https://example.gov.au/sa-bounded-version-fixture'
    from arsia_pipeline.source_identity import canonical_source_identity
    from test_source_identity import admitted
    family=canonical_source_identity(admitted(url),{'source':{'dataset_url':url}})['identity_key']
    files=[{'id':'test','sha256':marker*64,'size':100}]
    raw=independent_versions.inputs({'resources':[{'file_id':'test'}]},files)
    source=independent_versions.source_id(family,raw)
    scope={'version':independent_versions.VERSION,'family_identity_key':family,
        'input_sha256':raw,'cross_version_record_mapping':'unverified'}
    r=candidate(job,source,[row(source,k) for k in keys],dataset_url=url,version_scope=scope,source_files=files)
    return r


def test_independent_versions_single_query_replay_and_failure_preserve_release(client):
    existing={item['source_id'] for item in query.catalog()['sources']}
    first=claim_specific(queued(client)['id']);old=version_candidate(first,'a',['old-1','old-2'])
    worker.publish(first,old,lambda:None)
    second=claim_specific(queued(client)['id']);new=version_candidate(second,'b',['new-1','new-2'])
    worker.publish(second,new,lambda:None)
    catalog=query.catalog();assert {item['source_id'] for item in catalog['sources']} - existing == {old['source_id'],new['source_id']}
    for result in (old,new):
        q=query.query(result['source_id'],catalog['release_id'],'2024-01-01','2024-12-31')
        assert q['summary']['crash_count']==2
    replay=claim_specific(queued(client)['id']);again=version_candidate(replay,'a',['old-1','old-2'])
    worker.publish(replay,again,lambda:None)
    assert store.get_job(replay['id'])['status']=='no_change'
    assert query.catalog()==catalog
    bad=claim_specific(queued(client)['id']);rejected=version_candidate(bad,'c',['bad'])
    Path(rejected['canonical_path']).write_text('{}\n')
    with pytest.raises(Exception):worker.publish(bad,rejected,lambda:None)
    assert query.catalog()==catalog


def test_engineering_handoff_preserves_budget_and_durable_blocker(client):
    from arsia_pipeline.errors import UnsupportedCapability
    s=scoped(session_for(client)); b=bridge_for(s)
    try:
        repair_context.record(s,UnsupportedCapability('FIXTURE_MISSING_READER','Controlled fixture lacks a reader'),'inspect_bundle')
        before=dict(s.usage)
        out,error=b.tool('request_engineering_repair',{'blocker_id':s.runtime_state['repair']['blocker_id'],
            'proposal':'Controlled fixture: implement a bounded reader in isolated source, then test malformed lengths and path escapes.'})
        assert error and b.terminal and not s.ready
        assert s.usage['tool_calls']==before['tool_calls']+1
        packets=list(s.work_dir.glob('engineering-*.json'));assert len(packets)==1
        assert '"automatic_load_allowed": false' in packets[0].read_text()
    finally:b.stop()


def test_diagnostic_uses_exact_admitted_attempt_path_and_rejects_other_attempt(client):
    import hashlib
    from arsia_pipeline import task_authority, task_diagnostics, config
    from arsia_pipeline.scoped_orphans import OrphanRecoveryBlocked
    created=client.post('/jobs',json={'label':'Owned diagnostic path fixture'}).json()
    client.put('/jobs/'+created['id']+'/files',params={'filename':'unknown.csv'},content=b'event,when,outcome\n1,2020-01-01,Injury\n').raise_for_status()
    client.post('/jobs/'+created['id']+'/submit',json={}).raise_for_status()
    job=claim_specific(created['id']);work=job['work_dir']/'agent';work.mkdir()
    s=scoped(agent.AgentSession(job['files'],work,{},lambda *a,**k:None,lambda:None,job))
    f=s.files[0]
    task_authority.review(s,{'file_id':f['id'],'purpose':'crash_intake','bindings':{'key':'event','date':'when','outcome':'outcome'}})
    issue=repair_context.record(s,NeedsInput('Fixture needs full key comparison'),'intake')
    code='import csv, json\ndef adapt(ctx):\n    with open(next(iter(ctx.input_paths.values()))) as f:\n        n=sum(1 for _ in csv.DictReader(f))\n    (ctx.output_dir/"report.json").write_text(json.dumps({"rows":n}))\n'
    args={'blocker_id':issue['blocker_id'],'file_ids':[f['id']],'purpose':'key_relationships','code':code}
    before=s.usage['compute_seconds']
    result=task_diagnostics.run(s,args)
    assert result['status']=='succeeded' and result['report']=={'rows':1}
    assert result['admission'] is False and not s.validated and not s.ready
    assert Path(result['output_dir']).parent.parent==work
    assert s.usage['compute_seconds']>before
    assert hashlib.sha256(Path(f['path']).read_bytes()).hexdigest()==f['sha256']
    old=s.work_dir;s.work_dir=work/'sibling'
    try:
        with pytest.raises(OrphanRecoveryBlocked):task_diagnostics.run(s,args)
        assert not s.ready
    finally:s.work_dir=old
