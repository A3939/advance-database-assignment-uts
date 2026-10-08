"""Synthetic exact duplicates traverse actual independent QA, DB and Web service."""
from pathlib import Path
import json

from test_backend import isolated_database, client, claim_specific
from test_row_preprocessing import fixture
from arsia_pipeline import config, agent, worker, store
from arsia_pipeline.adapter_reuse import ADAPTER, controlled


def test_original_row_accounting_survives_publication_and_web(client,monkeypatch):
    root=config.ROOT/'duplicate-source-fixture';root.mkdir()
    contract,files=fixture(root)
    job_id=client.post('/jobs',json={'label':'Synthetic duplicate record acceptance'}).json()['id']
    client.put(f'/jobs/{job_id}/files',params={'filename':'duplicates.csv'},content=Path(files[0]['path']).read_bytes()).raise_for_status()
    client.post(f'/jobs/{job_id}/submit',json={}).raise_for_status()
    job=claim_specific(job_id);work=job['work_dir']/'agent';work.mkdir()
    session=agent.AgentSession(job['files'],work,job['options'],lambda *a,**k:None,lambda:None,job)
    controlled(session,'inspect_bundle',{})
    from source_binding_fixture import install_references
    install_references(session,files)
    contract['resources'][0]['file_id']=session.files[0]['id']
    session.documents={d['document_id']:d for d in contract.pop('documents')}
    controlled(session,'set_source_contract',{'contract':contract})
    controlled(session,'write_adapter',{'code':ADAPTER,'reason':'Preserve every raw row destination; collapse only exact same-key retransmissions'})
    for mode in ('sample','full'):
        run=controlled(session,'run_adapter',{'mode':mode})
        controlled(session,'validate_candidate',{'run_id':run['run_id']})
    rows=[json.loads(s) for s in Path(session.validated['canonical_path']).read_text().splitlines()]
    assert [(r['raw_key'],r['row_locator'],r['extensions']['Note']) for r in rows]==[
        (['001'],'csv:1','First'),(['002'],'csv:2','Second')]
    assert session.validated['summary']['raw_record_count']==4
    controlled(session,'register_adapter',{});controlled(session,'publish_candidate',{})
    assert worker.publish(job,session.ready,lambda:None)=='succeeded'
    saved=store.get_job(job_id)
    with store.connect() as conn:
        actual=conn.execute("SELECT payload->'raw_key' AS raw_key FROM canonical_crash WHERE batch_id=%s ORDER BY payload->>'record_id'",(saved['batch_id'],)).fetchall()
    assert actual==[{'raw_key':['001']},{'raw_key':['002']}]
    query=client.get('/query',params={'release_id':saved['release_id'],'source_id':saved['source_id'],'from':'2024-01-01','to':'2024-12-31'}).json()
    assert query['summary']=={'crash_count':2,'fatal_crash_count':None,'fatalities':None,'casualties':None}
    assert query['row_preprocessing']['raw_rows']==4
    assert query['row_preprocessing']['collapsed_duplicate_rows']==2
    cfg=config.read_config();monkeypatch.setenv('ARSIA_ACCEPTANCE_INSTANCE',cfg['instance_id'])
    from tools.acceptance_web import verify
    verify(Path(cfg['storage_home']),saved,{'rows':2,'fatal_crashes':None,'duplicates':2})
