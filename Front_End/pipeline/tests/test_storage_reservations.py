import json
import sqlite3
import subprocess
from pathlib import Path
from uuid import uuid4
import pytest
from arsia_pipeline.storage_catalog import TestSpace
from arsia_pipeline import storage_reservations as reservations
from arsia_pipeline.storage_restore import explicit_absence,inspect_optional
from arsia_pipeline.storage_lifecycle import StorageError,atomic_json,provision,sha
from arsia_pipeline.test_session import TestSession

@pytest.mark.parametrize('kind,text',[('volume','Error response from daemon: get Exact-Volume: no such volume'),
    ('volume','Error: No such volume: Exact-Volume'),('volume','ERROR RESPONSE FROM DAEMON: GET Exact-Volume: NO SUCH VOLUME'),
    ('container','Error: No such object: Exact-Volume'),('container','Error response from daemon: No such container: Exact-Volume')])
def test_absence_exact_complete_message(kind,text):
    assert explicit_absence(kind,'Exact-Volume',1,(' \t'+text+'\n').encode())

@pytest.mark.parametrize('kind,code,text',[
    ('volume',0,'Error: No such volume: exact'),('volume',2,'Error: No such volume: exact'),
    ('volume',1,'Error: No such volume: EXACT'),('volume',1,'Error: No such object: exact'),
    ('container',1,'Error: No such volume: exact'),('volume',1,'permission denied: No such volume: exact'),
    ('volume',1,'Error: No such volume: exact\npermission denied'),('volume',1,'Error: No such volume: other'),
    ('volume',1,'Error response from daemon: get exact: no such volume; timeout'),
    ('volume',1,'Error response from daemon: get other: no such volume'),
    ('volume',1,'Cannot connect to the Docker daemon'),('volume',1,'socket timeout'),
    ('volume',1,'Not found: exact'),('image',1,'Error: No such object: exact')])
def test_absence_errors_conflicts_and_other_identity_rejected(kind,code,text):
    assert not explicit_absence(kind,'exact',code,text)

@pytest.mark.parametrize('kind,raw',[(kind,raw) for kind in ['container','volume'] for raw in ['','{}','[]','[null]','[{},{}]','[{}]','not-json']]+[
    ('volume','[{"Name":"foreign"}]'),('volume','[{"Name":"exact","Mounts":[]}]'),
    ('container','[{"Name":"/exact","Id":"expected","Config":{}}]'),
    ('container','[{"Name":"/foreign","Id":"other","Config":{},"State":{}}]')])
def test_malformed_success_never_absent(monkeypatch,kind,raw):
    monkeypatch.setattr('arsia_pipeline.storage_restore.docker',lambda *a,**kw:raw.encode())
    with pytest.raises(StorageError):inspect_optional(kind,'exact')

@pytest.mark.parametrize('error',[subprocess.TimeoutExpired('docker',.1),OSError('socket unavailable')])
def test_inspect_transport_fails_closed(monkeypatch,error):
    def call(*a,**kw):raise error
    monkeypatch.setattr('arsia_pipeline.storage_restore.docker',call)
    with pytest.raises(StorageError):inspect_optional('volume','exact')

@pytest.fixture
def space(tmp_path):return TestSpace.create(tmp_path/'new-space',reserve_bytes=0)

def operation(space,kind='create'):
    return reservations.intent(space,kind,uuid4().hex,uuid4().hex,space.root/uuid4().hex,
        {'name':'exact-'+uuid4().hex,'volume':'exact-volume-'+uuid4().hex,'image':'sha256:test'})

def reserve(space,op,amount=512):
    identity=uuid4().hex;owner=uuid4().hex
    space.reserve(identity,amount,'unit',binding={'operation_id':op['operation_id'],'owner_token':owner})
    return next(r for r in reservations.status(space)['records'] if r['id']==identity)

def test_append_migration_legacy_stays_charged_no_implicit_release(tmp_path):
    space=TestSpace.create(tmp_path/'legacy-copy',reserve_bytes=0)
    with space.db() as db:
        db.execute('DROP TABLE reservations');db.execute('DROP TABLE reservation_operations');db.execute('DROP TABLE catalog_migrations')
        db.execute('CREATE TABLE reservations(id TEXT PRIMARY KEY, bytes INTEGER NOT NULL, reason TEXT NOT NULL)')
        db.execute('INSERT INTO reservations VALUES(?,?,?)',('old',123456,'restore verification peak'))
    before=sha(space.path);assert reservations.status(space)['active_bytes']==123456;assert sha(space.path)==before
    reservations.migrate(space);reservations.migrate(space)
    assert reservations.status(space)['records'][0]['state']=='legacy_unresolved'
    result=reservations.reconcile(space,apply=True);assert result['active_bytes']==123456
    assert result['results'][0]['code']=='LEGACY_UNRESOLVED'
    with pytest.raises(StorageError):space.release('old')

def test_intent_before_budget_refusal_has_no_target_home(space):
    op=operation(space);row_count=len(reservations.status(space)['operations'])
    with pytest.raises(StorageError):reserve(space,op,space.marker['policy']['budget_bytes']+1)
    assert not Path(op['home']).exists() and len(reservations.status(space)['records'])==0 and row_count==1

def test_peak_identity_and_audit_survive_release(space,monkeypatch):
    op=operation(space);monkeypatch.setattr(reservations,'settle',lambda *a,**kw:{'result':'completed','held_resources':[]})
    with space.peak(100,'specific execution',operation=op):
        row=reservations.status(space)['records'][0];assert row['state']=='active' and row['operation_id']==op['operation_id']
        assert space.measure()['operation_reserved_bytes']==100
    row=reservations.status(space)['records'][0]
    assert row['state']=='released' and row['released_at'] and row['evidence'] and space.measure()['operation_reserved_bytes']==0

def test_exception_peak_kept_until_explicit_resource_proof(space,monkeypatch):
    op=operation(space)
    with pytest.raises(RuntimeError):
        with space.peak(100,'specific execution',operation=op):raise RuntimeError('interrupted')
    assert reservations.status(space)['records'][0]['state']=='blocked'
    assert space.measure()['operation_reserved_bytes']==100
    monkeypatch.setattr('arsia_pipeline.storage_restore.inspect_optional',lambda *a:None)
    first=reservations.reconcile(space,apply=True);second=reservations.reconcile(space,apply=True)
    assert first['active_bytes']==second['active_bytes']==0 and second['results']==[]
    assert first['results'][0]['evidence']['exact_absence']

def test_live_operation_lock_defers_and_does_not_take_generation(space,monkeypatch):
    op=operation(space);row=reserve(space,op)
    monkeypatch.setattr(reservations,'settle',lambda *a,**kw:pytest.fail('live owner must not be settled'))
    with reservations.execution_lock(space,op['operation_id']):
        result=reservations.reconcile(space,apply=True)
    assert result['active_bytes']==512 and result['results'][0]['status']=='deferred'
    assert reservations.status(space)['records'][0]['generation']==row['generation']

def test_stale_owner_cannot_release_and_no_double_subtraction(space):
    op=operation(space);row=reserve(space,op)
    with space.db() as db:db.execute('UPDATE reservations SET generation=1,owner_token=? WHERE id=?',('new-owner',row['id']))
    with pytest.raises(StorageError):reservations.release(space,row,row['owner_token'],0,{'result':'stale'})
    assert reservations.status(space)['active_bytes']==512
    reservations.release(space,row,'new-owner',1,{'result':'settled'})
    with pytest.raises(StorageError):reservations.release(space,row,'new-owner',1,{'result':'twice'})
    assert reservations.status(space)['active_bytes']==0

@pytest.mark.parametrize('fault',['intent','space','unknown_resource','partial_home','docker_error'])
def test_unproven_operation_remains_charged(space,monkeypatch,fault):
    op=operation(space);row=reserve(space,op)
    monkeypatch.setattr('arsia_pipeline.storage_restore.inspect_optional',lambda *a:None)
    if fault=='intent':
        with space.db() as db:db.execute("UPDATE reservation_operations SET intent=replace(intent,'sha256:test','sha256:foreign')")
    elif fault=='space':
        with space.db() as db:db.execute("UPDATE reservations SET space_id='foreign'")
    elif fault=='unknown_resource':monkeypatch.setattr('arsia_pipeline.storage_restore.inspect_optional',lambda *a:{'Name':'unregistered'})
    elif fault=='partial_home':Path(op['home']).mkdir()
    else:
        def call(*a):raise StorageError('STORAGE_DOCKER_CHECK','daemon unavailable')
        monkeypatch.setattr('arsia_pipeline.storage_restore.inspect_optional',call)
    result=reservations.reconcile(space,apply=True)
    assert result['active_bytes']==512 and result['results'][0]['status']=='blocked'

def test_read_only_plan_keeps_bytes_and_does_not_inspect(space,monkeypatch):
    reserve(space,operation(space));before=sha(space.path)
    monkeypatch.setattr(reservations,'settle',lambda *a,**kw:pytest.fail('plan must not inspect or change resources'))
    reservations.status(space);result=reservations.reconcile(space,apply=False)
    assert sha(space.path)==before and result['active_bytes']==512 and not (space.root/'operation-locks').exists()

def test_reconciliation_limit_and_unrelated_rows(space,monkeypatch):
    for i in range(3):reserve(space,operation(space))
    monkeypatch.setattr('arsia_pipeline.storage_restore.inspect_optional',lambda *a:None)
    result=reservations.reconcile(space,apply=True,limit=1)
    assert len(result['results'])==1 and result['pending']==2 and result['active_bytes']==1024

def enrolled(space):
    cfg=provision(space.root/'registered',uuid4().hex,suite='test');cfg.update(storage_space=str(space.root),storage_space_id=space.marker['space_id'])
    s=TestSession(cfg);s.update(retention_family='test');atomic_json(s.ledger.root/'runtime.json',cfg);space.register(s,'test')
    return s

@pytest.mark.parametrize('kind',['backup','restore','create'])
def test_live_session_lock_defers_each_kind(space,monkeypatch,kind):
    s=enrolled(space);op=reservations.intent(space,kind,s.cfg['instance_id'],s.cfg['test_session_id'],s.ledger.home,{'name':'exact','volume':'exact','image':'image'})
    reserve(space,op)
    with s.ledger.lock():result=reservations.reconcile(space,apply=True)
    assert result['active_bytes']==512 and result['results'][0]['status']=='deferred'

def test_retained_restore_remains_charged_after_peak_release(space,monkeypatch):
    s=enrolled(space);op=reservations.intent(space,'restore',s.cfg['instance_id'],s.cfg['test_session_id'],s.ledger.home,{'name':'copy','volume':'copy-data','image':'image'})
    restore={'version':'restore-v2','operation_id':op['operation_id'],'name':'copy','volume':'copy-data','image':'image','state':'blocked'}
    s.ledger.operation(op['operation_id'],'restore',restore);reserve(space,op)
    monkeypatch.setattr(TestSession,'recover_helpers',lambda s:None)
    monkeypatch.setattr('arsia_pipeline.storage_restore.RestoreOperation.reconcile',lambda self,*a,**kw:restore)
    monkeypatch.setattr('arsia_pipeline.storage_restore.RestoreOperation.own',lambda self,op:(None,{'Name':'copy-data'}))
    result=reservations.reconcile(space,apply=True)
    assert result['active_bytes']==0 and result['results'][0]['evidence']['held_resources']
    assert any(r.get('operation')==op['operation_id'] for r in space.measure()['unknown_components'])

def test_failure_retention_first_last_per_fingerprint(space,monkeypatch):
    sessions=[]
    for i,fp in enumerate(['A','B','A','A','B']):
        cfg=provision(space.root/('run-'+str(i)),uuid4().hex,suite='failure')
        cfg.update(storage_space=str(space.root),storage_space_id=space.marker['space_id'])
        s=TestSession(cfg);s.update(retention_family='same');atomic_json(s.ledger.root/'runtime.json',cfg);space.register(s,'same')
        s.update(state='retained',success=False,failure_fingerprint=fp,closed_at='2026-10-01T00:00:0'+str(i)+'+00:00');space.update(s);sessions.append(s)
    called=[]
    def archive(s):called.append(s.cfg['test_session_id']);s.update(state='archived')
    monkeypatch.setattr(TestSession,'archive_database',archive)
    space.pin(sessions[2].cfg['test_session_id'],'diagnostic');space.retain(sessions[-1]);assert not called
    space.pin(sessions[2].cfg['test_session_id'],None);space.retain(sessions[-1])
    assert called==[sessions[2].cfg['test_session_id']]

def test_peak_to_resource_transfer_is_atomic_and_audited(space):
    op=operation(space);row=reserve(space,op)
    proof={'result':'settled','session_id':op['session_id'],
        'held_resources':[{'identity':op['expected']['volume'],'bytes':256,'category':'database_volume'}],
        'observed_resources':[{'identity':op['expected']['volume'],'present':True}]}
    reservations.release(space,row,row['owner_token'],0,proof)
    assert space.measure()['operation_reserved_bytes']==0
    assert space.measure()['docker_reserved_bytes']==256
    with space.db() as db:
        assert db.execute('SELECT bytes FROM reservation_resource_holds').fetchone()[0]==256
        assert db.execute("SELECT count(*) FROM journal WHERE event='reservation_released'").fetchone()[0]==1

def test_concurrent_transfer_after_measurement_still_counts_in_reserve(space,monkeypatch):
    original=space.check_budget
    def measured_then_transfer(amount):
        value=original(amount)
        with space.db() as db:db.execute('INSERT INTO reservation_resource_holds VALUES(?,?,?,?,?,?)',
            ('concurrent-volume',space.marker['policy']['budget_bytes'],'other','session','database_volume','now'))
        return value
    monkeypatch.setattr(space,'check_budget',measured_then_transfer)
    with pytest.raises(StorageError,match='Concurrent reservation'):reserve(space,operation(space),1)
    assert reservations.status(space)['active_bytes']==0

@pytest.mark.parametrize('kind',['create','backup','restore'])
def test_each_operation_intent_bound_before_peak_and_interrupt(space,monkeypatch,kind):
    op=operation(space,kind)
    def boundary(phase,payload):
        assert phase=='reserved' and payload==op
        row=reservations.status(space)['records'][0]
        assert reservations.checked_intent(space,row)==op
        assert row['state']=='active' and not Path(op['home']).exists()
        raise RuntimeError('before resource')
    monkeypatch.setattr(reservations,'_TEST_OPERATION_HOOK',boundary)
    with pytest.raises(RuntimeError):
        with space.peak(512,'boundary',operation=op):pytest.fail('must not reach allocation')
    assert reservations.status(space)['active_bytes']==512
