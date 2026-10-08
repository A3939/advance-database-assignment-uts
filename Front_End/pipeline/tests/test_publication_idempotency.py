from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import copy
import pytest
from test_backend import isolated_database,client,queued,claim_specific
from test_autonomous_backend import row,candidate,published
from arsia_pipeline import publication,query,registry,store


def prepared(client,source,rows,**opts):
    job=claim_specific(queued(client)['id'])
    return job,candidate(job,source,rows,**opts)


def test_different_code_is_freshly_audited_no_change(client):
    source='idempotency_'+uuid4().hex
    a,ra=published(client,source,[row(source,'a')])
    job,b=prepared(client,source,[row(source,'a')],version='different formatting / variable')
    assert b['admission']['adapter_sha256']!=ra['admission']['adapter_sha256']
    assert publication.publish(job,b,lambda:None)=='no_change'
    after=store.get_job(job['id'])
    assert after['release_id']==a['release_id']
    audit=after['result']['publication_evidence']
    assert audit['reason']=='same_publication_content'
    assert audit['candidate_validation']['admission']==b['admission']
    assert audit['candidate_validation']['adapter_version_id']==b['adapter_version_id']
    assert after['result']['admission']['adapter_sha256']==ra['admission']['adapter_sha256']


def test_same_execution_fingerprint_cannot_hide_changed_output(client):
    source='output_'+uuid4().hex
    a,ra=published(client,source,[row(source,'a')])
    job,b=prepared(client,source,[row(source,'a',fatalities=2)],mode='incremental')
    b['fingerprint']=ra['fingerprint']
    assert publication.publish(job,b,lambda:None)=='succeeded'
    after=store.get_job(job['id'])
    assert after['release_id']!=a['release_id']
    assert after['result']['summary']['fatalities']==2


def test_old_content_with_new_code_cannot_roll_back_later_update(client):
    source='history_'+uuid4().hex
    first,original=prepared(client,source,[row(source,'a')])
    original['files']=[{'id':'test','sha256':'a'*64}]
    publication.publish(first,original,lambda:None)
    a=store.get_job(first['id'])
    b,_=published(client,source,[row(source,'a',fatalities=3)],mode='incremental')
    job,r=prepared(client,source,[row(source,'a')],version='new compiler')
    r['files']=[{'id':'test','sha256':'a'*64}]
    assert publication.publish(job,r,lambda:None)=='no_change'
    c=store.get_job(job['id'])
    assert c['release_id']==b['release_id'] and c['result']['summary']['fatalities']==3
    audit=c['result']['publication_evidence']
    assert audit['reason']=='historical_input_replay'
    assert audit['reused_candidate_batch_id']==a['batch_id']
    assert audit['reused_batch_id']==b['batch_id']


def test_concurrent_equal_candidates_create_one_effective_release(client):
    source='concurrent_'+uuid4().hex
    jobs=[prepared(client,source,[row(source,'a')],version=str(i)) for i in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda pair:publication.publish(*pair,lambda:None),jobs))
    assert sorted(results)==['no_change','succeeded']
    after=[store.get_job(j['id']) for j,_ in jobs]
    assert after[0]['release_id']==after[1]['release_id']
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE source_id=%s',(source,)).fetchone()['n']==1

@pytest.mark.parametrize('change',['definition','permission','coverage'])
def test_same_rows_new_semantics_are_not_silently_ignored(client,change):
    source='semantic_'+change+'_'+uuid4().hex
    first,_=published(client,source,[row(source,'a')])
    job,r=prepared(client,source,[row(source,'a')])
    if change=='definition':r['source_contract']['definitions']['meaning']='Revised source metric definition'
    elif change=='permission':r['source_contract']['source']['licence']='Different permitted usage'
    else:
        r['source_contract']['update']['from']='2024-01-02'
    code=registry.read(r['adapter_version_id'])['code']
    r['admission']['source_contract_sha256']=registry.execution_contract_hash(r['source_contract'])
    r.update(registry.register(code,r['source_contract'],r))
    assert publication.publish(job,r,lambda:None)=='succeeded'
    assert store.get_job(job['id'])['release_id']!=first['release_id']


def test_new_input_matching_older_content_is_not_mislabeled_replay(client):
    source='not_replay_'+uuid4().hex
    a,ra=prepared(client,source,[row(source,'a')]);ra['files']=[{'id':'test','sha256':'a'*64}]
    publication.publish(a,ra,lambda:None)
    b,_=published(client,source,[row(source,'a',fatalities=2)],mode='incremental')
    c,rc=prepared(client,source,[row(source,'a')],version='new official input')
    rc['files']=[{'id':'test','sha256':'b'*64}]
    assert publication.publish(c,rc,lambda:None)=='succeeded'
    assert store.get_job(c['id'])['release_id']!=b['release_id']


def test_legacy_batch_without_publication_identity_preserves_history(client):
    source='legacy_'+uuid4().hex
    a,original=published(client,source,[row(source,'a')])
    with store.connect() as conn:
        conn.execute("UPDATE batches SET result=result-'publication_identity' WHERE id=%s",(a['batch_id'],))
    b,_=published(client,source,[row(source,'a',fatalities=4)],mode='incremental')
    job,r=prepared(client,source,[row(source,'a')])
    assert r['fingerprint']==original['fingerprint']
    assert publication.publish(job,r,lambda:None)=='no_change'
    after=store.get_job(job['id'])
    assert after['release_id']==b['release_id'] and after['result']['summary']['fatalities']==4
    assert after['result']['publication_evidence']['reason']=='historical_input_replay'
