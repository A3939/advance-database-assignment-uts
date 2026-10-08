"""Explicit unverified auxiliary rows remain excluded from derived unit metrics."""
from pathlib import Path

from test_backend import isolated_database, client, claim_specific
from test_retained_resources import fixture, REASON
from arsia_pipeline import config, agent, worker, store
from arsia_pipeline.adapter_reuse import ADAPTER, controlled


def test_crash_count_remains_available_while_auxiliary_linkage_stays_unverified(client,monkeypatch):
    root=config.ROOT/'retained-auxiliary-fixture';root.mkdir()
    contract,files=fixture(root)
    job_id=client.post('/jobs',json={'label':'Synthetic unresolved auxiliary acceptance'}).json()['id']
    for f in [f for f in files if f.get('role')!='public_evidence']:
        client.put(f'/jobs/{job_id}/files',params={'filename':f['name']},content=Path(f['path']).read_bytes()).raise_for_status()
    client.post(f'/jobs/{job_id}/submit',json={}).raise_for_status()
    job=claim_specific(job_id);work=job['work_dir']/'agent';work.mkdir()
    session=agent.AgentSession(job['files'],work,job['options'],lambda *a,**k:None,lambda:None,job)
    controlled(session,'inspect_bundle',{})
    from source_binding_fixture import install_references
    install_references(session,files)
    actual={f['sha256']:f['id'] for f in session.files if f.get('role')!='public_evidence'}
    contract['resources'][0]['file_id']=actual[files[0]['sha256']]
    contract['retained_resources'][0]['file_id']=actual[files[1]['sha256']]
    session.documents={d['document_id']:d for d in contract.pop('documents')}
    controlled(session,'set_source_contract',{'contract':contract})
    controlled(session,'write_adapter',{'code':ADAPTER,'reason':'Publish only independently verified crash facts; unresolved units retained with explicit limitations'})
    for mode in ('sample','full'):
        run=controlled(session,'run_adapter',{'mode':mode})
        controlled(session,'validate_candidate',{'run_id':run['run_id']})
    assert session.validated['summary']['crash_count']==1
    assert session.validated['summary']['raw_record_count']==3
    assert session.validated['summary']['retained_unverified_record_count']==2
    controlled(session,'register_adapter',{});controlled(session,'publish_candidate',{})
    assert worker.publish(job,session.ready,lambda:None)=='succeeded'
    saved=store.get_job(job_id)
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM canonical_crash WHERE batch_id=%s',(saved['batch_id'],)).fetchone()['n']==1
        assert conn.execute('SELECT count(*) AS n FROM canonical_unit WHERE batch_id=%s',(saved['batch_id'],)).fetchone()['n']==0
    query=client.get('/query',params={'release_id':saved['release_id'],'source_id':saved['source_id'],'from':'2024-01-01','to':'2024-12-31'}).json()
    assert query['summary']=={'crash_count':1,'fatal_crash_count':None,'fatalities':None,'casualties':None}
    assert query['units']['status']=='unavailable'
    unit_limit=next(v for v in query['capability_limits'] if v['capability']=='units')
    assert unit_limit['requested'] and not unit_limit['target_satisfied'] and unit_limit['reason']==REASON
    cfg=config.read_config();monkeypatch.setenv('ARSIA_ACCEPTANCE_INSTANCE',cfg['instance_id'])
    from tools.acceptance_web import verify
    verify(Path(cfg['storage_home']),saved,{'rows':1,'fatal_crashes':None,'limited':REASON})
