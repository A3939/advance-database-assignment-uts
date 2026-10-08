"""Synthetic PostgreSQL transaction boundary checks, no official data claims."""
import pytest
from test_backend import isolated_database,client,queued,claim_specific
from test_autonomous_backend import row,published,candidate
from arsia_pipeline import publication,query,store
from arsia_pipeline.errors import NeedsInput


def bounded(job,source,rows):
    r=candidate(job,source,rows,mode='incremental',last='2024-01-31')
    r.setdefault('admission',{}).setdefault('evidence',{})['representation_proofs']=[{'synthetic_test':True}]
    return r


def test_month_subset_preserves_outside_payload(client):
    source='synthetic_month_subset'
    old=row(source,'older',2023);old['occurrence_date']='2023-01-05'
    now=row(source,'current',2024);now['occurrence_date']='2024-01-05'
    first,_=published(client,source,[old,now],first='2023-01-01')
    with store.connect() as conn:
        before=conn.execute("SELECT payload FROM canonical_crash WHERE batch_id=%s AND payload->>'row_locator'=%s",(first['batch_id'],old['row_locator'])).fetchone()['payload']
    job=claim_specific(queued(client)['id']);publication.publish(job,bounded(job,source,[now]),lambda:None)
    second=store.get_job(job['id'])
    with store.connect() as conn:
        after=conn.execute("SELECT payload FROM canonical_crash WHERE batch_id=%s AND payload->>'row_locator'=%s",(second['batch_id'],old['row_locator'])).fetchone()['payload']
    assert before==after and second['status']=='succeeded'


def test_outside_key_collision_stops_atomically(client):
    source='synthetic_scope_collision'
    old=row(source,'same',2023);old['occurrence_date']='2023-01-05'
    first,_=published(client,source,[old],first='2023-01-01')
    before=query.catalog();new=row(source,'same',2024);new['occurrence_date']='2024-01-05'
    job=claim_specific(queued(client)['id'])
    with pytest.raises(NeedsInput,match='outside its authorized'):
        publication.publish(job,bounded(job,source,[new]),lambda:None)
    assert query.catalog()==before
    with store.connect() as conn:assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s',(job['id'],)).fetchone()['n']==0
