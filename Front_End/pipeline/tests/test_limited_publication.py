"""A synthetic missing-CRS source traverses real QA, registry, SQL and Web tools."""
from pathlib import Path
import json

from test_backend import isolated_database, client, claim_specific
from test_limited_geography import source_fixture
from arsia_pipeline import config, agent, worker, store
from arsia_pipeline.adapter_reuse import ADAPTER, controlled


def test_limited_nonspatial_source_publishes_and_remains_limited_everywhere(client,monkeypatch):
    root=config.ROOT/'limited-source-fixture';root.mkdir()
    contract,files=source_fixture(root)
    job_id=client.post('/jobs',json={'label':'Synthetic missing CRS acceptance'}).json()['id']
    client.put(f'/jobs/{job_id}/files',params={'filename':'limited.csv'},content=Path(files[0]['path']).read_bytes()).raise_for_status()
    client.post(f'/jobs/{job_id}/submit',json={}).raise_for_status()
    job=claim_specific(job_id);work=job['work_dir']/'agent';work.mkdir()
    session=agent.AgentSession(job['files'],work,job['options'],lambda *a,**k:None,lambda:None,job)
    controlled(session,'inspect_bundle',{})
    from source_binding_fixture import install_references
    install_references(session,files)
    contract['resources'][0]['file_id']=session.files[0]['id']
    session.documents={d['document_id']:d for d in contract.pop('documents')}
    controlled(session,'set_source_contract',{'contract':contract})
    controlled(session,'write_adapter',{'code':ADAPTER,'reason':'Synthetic independent nonspatial capability, requested map is unresolved'})
    for mode in ('sample','full'):
        run=controlled(session,'run_adapter',{'mode':mode})
        controlled(session,'validate_candidate',{'run_id':run['run_id']})
    # Literal source oracle; no shared projection creates expected values.
    rows=[json.loads(s) for s in Path(session.validated['canonical_path']).read_text().splitlines()]
    assert len(rows)==1 and rows[0]['raw_key']==['001']
    assert rows[0]['occurrence_date']=='2024-01-01' and rows[0]['coordinates'] is None
    assert rows[0]['extensions']=={'ID':'001','DATE':'2024-01-01','Event_X':'123','Event_Y':'456','Note':'Unexplained extra field'}
    controlled(session,'register_adapter',{});controlled(session,'publish_candidate',{})
    assert worker.publish(job,session.ready,lambda:None)=='succeeded'
    saved=store.get_job(job_id)
    with store.connect() as conn:
        actual=conn.execute("SELECT payload->'raw_key' AS raw_key,payload->>'record_id' AS source_key FROM canonical_crash WHERE batch_id=%s",(saved['batch_id'],)).fetchall()
    assert actual==[{'raw_key':['001'],'source_key':'["001"]'}]
    catalogue=client.get('/catalog',params={'release_id':saved['release_id']}).json()
    source=next(s for s in catalogue['sources'] if s['source_id']==saved['source_id'])
    assert source['capabilities']['geography'] is False
    limit=source['capability_limits'][0]
    assert limit['requested'] is True and limit['target_satisfied'] is False
    assert source['capability_review']['status']=='limited'
    query=client.get('/query',params={'release_id':saved['release_id'],'source_id':saved['source_id'],'from':'2024-01-01','to':'2024-12-31'}).json()
    assert query['summary']=={'crash_count':1,'fatal_crash_count':None,'fatalities':None,'casualties':None}
    assert query['geography']['status']=='unsupported' and query['coverage']['complete'] is False
    assert query['capability_limits']==source['capability_limits']
    cfg=config.read_config();monkeypatch.setenv('ARSIA_ACCEPTANCE_INSTANCE',cfg['instance_id'])
    from tools.acceptance_web import verify
    verify(Path(cfg['storage_home']),saved,{'rows':1,'fatal_crashes':None,'limited':limit['reason']})
