import json
import hashlib
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from uuid import uuid4
import pytest
from arsia_pipeline import upload_gc,input_store
from arsia_pipeline.storage_lifecycle import Ledger,provision,StorageError,atomic_json,REFERENCE_TABLES

class Rows:
 def __init__(self,rows):self.rows=rows
 def fetchall(self):return self.rows
class DB:
 def __init__(self):self.tables={k:[] for k in REFERENCE_TABLES}
 def execute(self,sql):return Rows(self.tables[sql.split(' FROM ')[1]])
@pytest.fixture
def managed(tmp_path,monkeypatch):
 cfg=provision(tmp_path/'home','gc-instance',suite='generic-gc');l=Ledger(cfg);m=l.session;m['state']='running';atomic_json(l.home/'session.json',m);db=DB()
 @contextmanager
 def locked(config):yield l,db
 monkeypatch.setattr(upload_gc,'maintenance',locked)
 return cfg,l,db

def make(cfg,l,payload=b'id,year\nalpha,2024\n',publish=True):
 jid=str(uuid4());fid=uuid4().hex;part=l.root/'uploads'/jid/(fid+'.part');part.parent.mkdir(parents=True)
 upload_gc.begin(cfg,part,jid,fid);part.write_bytes(payload)
 receipt={'id':fid,'job_id':jid,'name':'synthetic.csv','format':'csv','sha256':hashlib.sha256(payload).hexdigest(),'size':len(payload)}
 return (input_store.publish(cfg,part,receipt) if publish else receipt),part

def later():return datetime.now(timezone.utc)+timedelta(days=2)

def test_expired_pending_and_part_reclaimed_with_tombstones(managed):
 cfg,l,db=managed;r,p=make(cfg,l);r2,p2=make(cfg,l,b'other',False)
 before=upload_gc.reconcile(cfg,clock=later());assert all(x['action']=='quarantine' for x in before['results']);assert p2.exists()
 result=upload_gc.reconcile(cfg,apply=True,clock=later());assert all(x['action']=='reclaimed' for x in result['results']);assert not p2.exists() and not __import__('pathlib').Path(r['path']).exists()
 assert len(list((l.home/'tombstones').glob('*.json')))==2
 assert upload_gc.reconcile(cfg,apply=True,clock=later())['results']==[]

def test_sql_commit_missing_journal_reconciled(managed):
 cfg,l,db=managed;r,p=make(cfg,l);db.tables['jobs']=[{'id':r['job_id'],'status':'cancelled','files':[r]}]
 result=upload_gc.reconcile(cfg,apply=True,clock=later());assert result['results'][0]['action']=='committed'
 assert l.get_operation(r['id'])['state']=='committed' and input_store.resolve(cfg,r).exists()

def test_shared_blob_pending_rollback_keeps_success(managed):
 cfg,l,db=managed;ok,p=make(cfg,l);bad,_=make(cfg,l);db.tables['jobs']=[{'id':ok['job_id'],'status':'cancelled','files':[ok]}]
 result=upload_gc.reconcile(cfg,apply=True,clock=later());assert input_store.resolve(cfg,ok).exists()
 assert not (l.root/'receipts'/(bad['id']+'.json')).exists()
 assert l.get_operation(bad['id'])['state']=='reclaimed'

@pytest.mark.parametrize('fault',['grace','rollback_clock','lease','pin','active','checkpoint','symlink','unknown_time'])
def test_uncertainty_preserves_bytes(managed,fault):
 cfg,l,db=managed;r,p=make(cfg,l,publish=False);clock=later();op=l.get_operation(r['id'])
 if fault=='grace':clock=datetime.now(timezone.utc)+timedelta(hours=2)
 elif fault=='rollback_clock':clock=datetime.now(timezone.utc)-timedelta(days=1)
 elif fault=='lease':op['lease_until']=(clock+timedelta(days=1)).isoformat();l.operation(r['id'],'upload',op)
 elif fault=='pin':op['pin']='keep';l.operation(r['id'],'upload',op)
 elif fault=='active':db.tables['jobs']=[{'id':r['job_id'],'status':'needs_input','files':[]}]
 elif fault=='checkpoint':db.tables['agent_sessions']=[{'checkpoint':{'dependent_file':r['id']}}]
 elif fault=='unknown_time':op['created_at']=None;l.operation(r['id'],'upload',op)
 else:
  p.rename(p.with_name('source'));p.symlink_to(p.with_name('source'))
 result=upload_gc.reconcile(cfg,apply=True,clock=clock);assert result['results'][0]['action']=='retain';assert p.exists()

def test_unknown_staging_never_adopted(managed):
 cfg,l,db=managed;p=l.root/'unknown.part';p.write_bytes(b'not owned');assert upload_gc.reconcile(cfg,apply=True,clock=later())['results']==[];assert p.exists()

def test_progress_not_starved_by_terminal_operations(managed):
 cfg,l,db=managed
 for i in range(105):l.operation(str(i),'upload',{'state':'reclaimed','operation_id':str(i)})
 r,p=make(cfg,l,publish=False);assert upload_gc.reconcile(cfg,apply=True,clock=later())['results'][0]['action']=='reclaimed'
