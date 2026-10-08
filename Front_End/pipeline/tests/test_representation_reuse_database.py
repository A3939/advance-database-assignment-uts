"""Historical receipt + equivalent wrapper, and a controlled same-source version.

Synthetic official transport only. Actual executor, QA, registry, publication
and reads are used; neither QA nor expected business values are mocked.
"""
import copy
import csv
import io
import json
from pathlib import Path

from test_backend import isolated_database,client,claim_specific
from test_representation_binding import source
from source_binding_fixture import install_references,add_reference,URL
from arsia_pipeline import agent,config,worker,store,public_sources
from arsia_pipeline.adapter_reuse import ADAPTER,controlled,prepare


def test_historical_wrapper_and_controlled_version_use_no_models_but_fresh_qa(client,monkeypatch):
    cfg=config.read_config();assert cfg['autonomous_adaptation_v1'] is True
    root=config.ROOT/'source-fixture';root.mkdir()
    contract,files,original=source(root)
    contract['resources'][0]['source_url']=URL
    def new(data,name):
        ident=client.post('/jobs',json={'label':'Synthetic version and representation acceptance'}).json()['id']
        client.put(f'/jobs/{ident}/files',params={'filename':name},content=data).raise_for_status()
        client.post(f'/jobs/{ident}/submit',json={}).raise_for_status()
        job=claim_specific(ident);work=job['work_dir']/'agent';work.mkdir()
        return job,agent.AgentSession(job['files'],work,job['options'],lambda *a,**k:None,lambda:None,job)
    first,s=new(original.encode(),'original.csv');controlled(s,'inspect_bundle',{})
    install_references(s,files);contract['resources'][0]['file_id']=s.files[0]['id']
    s.documents={d['document_id']:d for d in contract.pop('documents')}
    controlled(s,'set_source_contract',{'contract':contract})
    controlled(s,'write_adapter',{'code':ADAPTER,'reason':'Initial fully verified synthetic version'})
    for mode in ('sample','full'):
        run=controlled(s,'run_adapter',{'mode':mode});controlled(s,'validate_candidate',{'run_id':run['run_id']})
    controlled(s,'register_adapter',{});controlled(s,'publish_candidate',{})
    assert worker.publish(first,s.ready,lambda:None)=='succeeded'
    initial=store.get_job(first['id'])
    # The reference receipt remains archived. Current network export need not
    # be identical or reachable to recognize a verified historical wrapper.
    second,replay=new(original.replace('\n','\r\n').encode('utf-16'),'repacked.csv')
    def no_network(*a,**k):raise AssertionError('Historical representation must not refetch or invoke AI')
    monkeypatch.setattr(public_sources.PublicSources,'fetch_public_source',no_network)
    ready=prepare(replay,cfg)
    assert ready and replay.usage['model_calls']==0
    assert replay.runtime_state['source_knowledge']['route']=='same_source_representation_candidate_requires_fresh_QA'
    assert {r['mode'] for r in replay.runs.values()}=={'sample','full'}
    assert worker.publish(second,ready,lambda:None) in {'succeeded','no_change'}
    after=store.get_job(second['id'])
    assert after['result']['summary']['crash_count']==2
    assert [(r['raw_key'],r['extensions']['Note']) for r in map(json.loads,Path(ready['canonical_path']).read_text().splitlines())]==[
        (['001'],'café, detail'),(['002'],'second')]
    # A real content change cannot be explained by the historical wrapper proof.
    # Simulate one new public CSV response at the same official fixture resource.
    changed=original.replace('second','new note')
    third,version=new(changed.encode(),'new-version.csv')
    fresh_file=root/'fresh.csv';fresh_file.write_text(changed)
    holder=[{'id':'temporary','path':str(fresh_file),'size':fresh_file.stat().st_size}]
    reference=add_reference(holder,root)
    docs=copy.deepcopy(s.documents)
    def current_export(self,url,**kwargs):
        if url==URL:
            receipt=json.loads(Path(reference['receipt_path']).read_text())
            return {**receipt,'file_id':reference['id'],'__files':[reference]}
        for doc in docs.values():
            if doc['url']==url:
                descriptor=copy.deepcopy(doc);descriptor['fetched_at']='2026-10-03T00:00:00+00:00'
                return {'status':'fetched','final_url':url,'sha256':doc['sha256'],
                    'fetched_at':descriptor['fetched_at'],'documents':[{'document_id':doc['document_id']}],
                    '__documents':[descriptor]}
        raise AssertionError('Unexpected fixture fetch')
    monkeypatch.setattr(public_sources.PublicSources,'fetch_public_source',current_export)
    ready=prepare(version,cfg)
    assert ready and version.usage['model_calls']==0, version.runtime_state
    assert version.runtime_state['source_knowledge']['route']=='same_source_version_candidate_requires_fresh_QA'
    assert {r['mode'] for r in version.runs.values()}=={'sample','full'}
    assert worker.publish(third,ready,lambda:None)=='succeeded'
    updated=store.get_job(third['id'])
    assert updated['release_id']!=initial['release_id']
    with store.connect() as conn:
        old=conn.execute("SELECT payload->'extensions'->>'Note' AS note FROM canonical_crash WHERE batch_id=%s AND payload->>'record_id'=%s",(initial['batch_id'],'["002"]')).fetchone()
        new_note=conn.execute("SELECT payload->'extensions'->>'Note' AS note FROM canonical_crash WHERE batch_id=%s AND payload->>'record_id'=%s",(updated['batch_id'],'["002"]')).fetchone()
    assert old['note']=='second' and new_note['note']=='new note'
    assert updated['result']['summary']['crash_count']==2 and updated['result']['summary']['fatalities'] is None
    query=client.get('/query',params={'source_id':updated['source_id'],'release_id':updated['release_id'],
        'from':'2024-01-01','to':'2024-12-31'}).json()
    assert query['coverage']['complete'] is False and query['summary']['crash_count']==2
    # Add and later remove unconsumed columns across several admitted templates.
    # Matching a schema alone cannot admit these inputs: each simulated current
    # official response binds every uploaded value, then full QA checks the rows.
    for index,columns in enumerate((['Extra','ID','DATE','Event_X','Event_Y','Note'],
                                     ['ID','DATE','Event_X','Event_Y'],
                                     ['DATE','ID','Event_Y','Event_X','Extra'])):
        rows=list(csv.DictReader(io.StringIO(changed)))
        text=io.StringIO(newline='');writer=csv.DictWriter(text,fieldnames=columns,extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            row['Extra']='uninterpreted '+row['ID'];writer.writerow(row)
        content=text.getvalue().encode('utf-8-sig')
        fresh_file=root/f'columns-{index}.csv';fresh_file.write_bytes(content)
        holder=[{'id':'temporary','path':str(fresh_file),'size':len(content)}]
        reference=add_reference(holder,root)
        job,variation=new(content,f'columns-{index}.csv')
        ready=prepare(variation,cfg)
        assert ready and variation.usage['model_calls']==0,variation.runtime_state
        assert {r['mode'] for r in variation.runs.values()}=={'sample','full'}
        assert worker.publish(job,ready,lambda:None)=='succeeded'
        payloads=list(map(json.loads,Path(ready['canonical_path']).read_text().splitlines()))
        assert [(r['raw_key'],r['occurrence_date']) for r in payloads]==[
            (['001'],'2024-01-01'),(['002'],'2024-02-02')]
        for payload,row in zip(payloads,rows):
            assert payload['extensions']=={key:row[key] for key in columns}
        assert ready['summary']['crash_count']==2 and ready['summary']['fatalities'] is None
    # A required field removal must route to investigation before fetching or
    # executing anything, despite the admitted optional-column variants.
    monkeypatch.setattr(public_sources.PublicSources,'fetch_public_source',no_network)
    missing=content.decode('utf-8-sig').replace('DATE,','').replace('2024-01-01,','').replace('2024-02-02,','')
    job,incomplete=new(missing.encode(),'missing-date.csv')
    assert prepare(incomplete,cfg) is None
    assert not incomplete.runs and incomplete.usage['model_calls']==0
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s',(job['id'],)).fetchone()['n']==0
