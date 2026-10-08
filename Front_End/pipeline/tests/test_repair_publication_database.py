"""Synthetic SQL composition oracle, distinct from official source admission."""
import copy
from uuid import uuid4
import pytest
from test_backend import isolated_database,client,queued,claim_specific
from test_autonomous_backend import row,candidate,published
from test_bounded_publication import bounded,test_month_subset_preserves_outside_payload,test_outside_key_collision_stops_atomically
from test_publication_idempotency import (test_different_code_is_freshly_audited_no_change,
 test_same_execution_fingerprint_cannot_hide_changed_output,test_old_content_with_new_code_cannot_roll_back_later_update,
 test_concurrent_equal_candidates_create_one_effective_release,test_same_rows_new_semantics_are_not_silently_ignored)
from arsia_pipeline import store,publication,query
from arsia_pipeline.errors import NeedsInput


def facts(batch,table):
 with store.connect() as db:return {r['payload']['record_id']:r['payload'] for r in db.execute('SELECT payload FROM '+table+' WHERE batch_id=%s',(batch,))}


def test_bounded_incremental_keeps_absent_parents_children_and_outside_rows(client):
 source='bounded_'+uuid4().hex
 old=row(source,'outside',2023,occurrence_date='2023-05-11',month=5)
 absent=row(source,'absent',occurrence_date='2024-01-03')
 changed=row(source,'changed',occurrence_date='2024-01-04')
 unit=row(source,'vehicle',role='unit',grain='unit',relations={'crash':changed['record_id']},crash_id=changed['record_id'])
 casualty=row(source,'person',role='casualty',grain='casualty',relations={'crash':absent['record_id']},crash_id=absent['record_id'])
 first,_=published(client,source,[old,absent,changed],units=[unit],casualties=[casualty],first='2023-01-01')
 original={t:facts(first['batch_id'],t) for t in ['canonical_crash','canonical_unit','canonical_casualty']}
 new=row(source,'new',occurrence_date='2024-01-15');updated={**changed,'fatalities':3}
 j=claim_specific(queued(client)['id']);r=bounded(j,source,[updated,new]);assert publication.publish(j,r,lambda:None)=='succeeded'
 after=store.get_job(j['id']);found=facts(after['batch_id'],'canonical_crash')
 assert set(found)=={old['record_id'],absent['record_id'],changed['record_id'],new['record_id']}
 assert found[old['record_id']]==old and found[absent['record_id']]==absent
 assert found[changed['record_id']]==updated and found[new['record_id']]==new
 for table in ['canonical_unit','canonical_casualty']:assert facts(after['batch_id'],table)==original[table]
 assert facts(first['batch_id'],'canonical_crash')==original['canonical_crash']
 # Same candidate, new execution identity: fresh registration, unchanged release.
 j2=claim_specific(queued(client)['id']);r2=bounded(j2,source,[updated,new]);assert publication.publish(j2,r2,lambda:None)=='no_change'
 assert store.get_job(j2['id'])['release_id']==after['release_id']


def test_first_incremental_does_not_claim_complete_coverage(client):
 source='first_'+uuid4().hex;j=claim_specific(queued(client)['id']);r=bounded(j,source,[row(source,'a',occurrence_date='2024-01-02')])
 assert publication.publish(j,r,lambda:None)=='succeeded'
 first=store.get_job(j['id']);assert first['result']['coverage_intervals']==[]
 for filename in ['same.geojson','renamed.geojson']:
  j=claim_specific(queued(client)['id']);r=bounded(j,source,[row(source,'a',occurrence_date='2024-01-02')]);r['files']=[{'id':'test','name':filename,'sha256':'a'*64}]
  assert publication.publish(j,r,lambda:None)=='no_change'
  after=store.get_job(j['id']);assert after['batch_id']==first['batch_id'] and after['release_id']==first['release_id']


def test_unproven_partition_removal_cannot_publish(client):
 source='no_delete_'+uuid4().hex
 first,_=published(client,source,[row(source,'a',occurrence_date='2024-01-01'),row(source,'b',occurrence_date='2024-01-02')])
 before=query.catalog();j=claim_specific(queued(client)['id']);r=candidate(j,source,[row(source,'a',occurrence_date='2024-01-01')],mode='partition',last='2024-01-31')
 # A synthetic loader candidate cannot turn partial membership into removal authority.
 with pytest.raises(NeedsInput):publication.publish(j,r,lambda:None)
 assert query.catalog()==before
 assert set(facts(first['batch_id'],'canonical_crash'))=={'["a"]','["b"]'}
