"""Actual upload, controlled tools, Docker, QA, registry and transaction/query.

Publisher evidence is explicitly synthetic. No model, QA or registry mock; this
proves the mechanism rather than claiming a real Victorian source was admitted.
"""
import copy
import json
from pathlib import Path

import pytest

from test_backend import isolated_database, client, claim_specific
from test_lookup_projection import bundle
from test_lookup_admission import configure_admissible, install_documents, CODE
from arsia_pipeline import agent, isolated_executor, store, query, worker


def test_lookup_upload_sample_full_registry_publish_query_and_repeat(client,tmp_path):
    if isolated_executor.docker(['image','inspect',isolated_executor.IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    base,seed=bundle(tmp_path)
    docs=configure_admissible(base,seed,tmp_path/'seed-evidence')
    contract=copy.deepcopy(base);contract.pop('documents')
    release=None
    for attempt in range(2):
        response=client.post('/jobs',json={'label':'Explicit synthetic lookup end-to-end','request_id':'lookup-mechanism-'+str(attempt)})
        assert response.status_code==200,response.text
        job_id=response.json()['id']
        for file in seed:
            name=('renamed-' if attempt else '')+file['name']
            assert client.put(f'/jobs/{job_id}/files',params={'filename':name},content=Path(file['path']).read_bytes()).status_code==200
        assert client.post(f'/jobs/{job_id}/submit',json={}).status_code==200
        job=claim_specific(job_id);work=job['work_dir']/'agent';work.mkdir()
        actual=job['files'];by_name={f['name'].removeprefix('renamed-'):f for f in actual}
        c=copy.deepcopy(contract)
        c['resources'][0]['file_id']=by_name['child.csv']['id'];c['lookup_tables'][0]['file_id']=by_name['codes.csv']['id']
        install_documents(c,docs,work/'evidence')
        session=agent.AgentSession(actual,work,{},lambda *a,**kw:None,lambda:None,job)
        session.documents={doc['document_id']:doc for doc in c.pop('documents')}
        session.execute_tool('set_source_contract',{'contract':c})
        # Neither registration nor full execution can bypass the sample gate.
        with pytest.raises(ValueError):session.execute_tool('register_adapter',{})
        with pytest.raises(ValueError,match='sample'):session.execute_tool('run_python',{'code':CODE,'mode':'full'})
        sample=session.execute_tool('run_python',{'code':CODE,'mode':'sample'})
        assert sample['status']=='succeeded',sample
        assert session.execute_tool('validate_candidate',{'run_id':sample['run_id']})['status']=='sample_only'
        full=session.execute_tool('run_python',{'mode':'full'})
        assert full['status']=='succeeded',full
        qa=session.execute_tool('validate_candidate',{'run_id':full['run_id']})
        assert qa['status']=='validated',qa
        registered=session.execute_tool('register_adapter',{})
        assert registered['adapter_version_id']
        assert session.execute_tool('publish_candidate',{})['status']=='accepted_for_atomic_publication'
        worker.publish(job,session.ready,lambda:None)
        completed=store.get_job(job_id)
        assert completed['status']==('no_change' if attempt else 'succeeded'),completed
        if attempt:assert completed['release_id']==release
        release=completed['release_id']
        result=query.query('independent_fixture',release,'2024-01-01','2024-12-31')
        assert result['summary']['crash_count']==2
        assert result['summary']['fatalities']==2 and result['summary']['casualties']==6
        with store.connect() as conn:
            rows=conn.execute('SELECT record_id,payload FROM canonical_crash WHERE batch_id=%s ORDER BY record_id',(completed['batch_id'],)).fetchall()
        assert len(rows)==2
        # Canonical record IDs are hashes; their order is not source row order.
        assert {tuple(r['payload']['raw_key']): r['payload']['lookup_lineage']['code']['parent']['row_locator']
                for r in rows}=={('001',):'csv:1',('002',):'csv:2'}
        assert session.usage['model_calls']==0
