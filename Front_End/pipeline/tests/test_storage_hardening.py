import json
import subprocess
from pathlib import Path
from uuid import uuid4
import pytest
from arsia_pipeline.storage_lifecycle import provision,Ledger,StorageError,atomic_json
from arsia_pipeline.test_session import TestSession,SESSION_LABEL,INSTANCE_LABEL
from arsia_pipeline.storage_restore import RestoreOperation,RESTORE_LABEL,inspect_optional
from arsia_pipeline.storage_catalog import TestSpace

@pytest.fixture
def restore_owner(tmp_path,monkeypatch):
    cfg=provision(tmp_path/'session','unit-parent',suite='restore-negative');s=TestSession(cfg)
    op={'version':'restore-v2','operation_id':uuid4().hex,'parent_instance':cfg['instance_id'],'parent_session':cfg['test_session_id'],
        'name':'only-recorded-restore','volume':'only-recorded-volume','container_id':'exact1234567890','image':'sha256:expected','state':'verified','purpose':'verify_only','pin':None,'lease':None}
    manager=RestoreOperation(s);labels=manager.labels(op)
    container={'Id':op['container_id'],'Name':'/'+op['name'],'Image':op['image'],'Config':{'Labels':labels.copy()},'State':{'Running':False,'ExitCode':0},
        'Mounts':[{'Type':'volume','Name':op['volume'],'Destination':'/var/lib/postgresql/data','RW':True}],'HostConfig':{'NetworkMode':'none','PortBindings':{}}}
    volume={'Name':op['volume'],'Labels':labels.copy(),'CreatedAt':'same'};users=[op['container_id']];calls=[]
    def docker(*args,**kw):
        calls.append(args)
        if args[0]=='inspect':return json.dumps([container]).encode()
        if args[:2]==('volume','inspect'):return json.dumps([volume]).encode()
        if args[0]=='ps':return '\n'.join(users).encode()
        raise AssertionError('Unexpected mutation '+str(args))
    from arsia_pipeline import storage_restore
    monkeypatch.setattr(storage_restore,'docker',docker)
    return manager,op,container,volume,users,calls

@pytest.mark.parametrize('fault',['instance','session','operation','container','volume','image','mount','network','shared','volume_time','marker'])
def test_restore_exact_identity_refuses_mutation(restore_owner,fault):
    m,op,c,v,users,calls=restore_owner
    if fault=='marker':(m.ledger.root/'.storage-owner.json').write_text('{}')
    elif fault=='instance':c['Config']['Labels'][INSTANCE_LABEL]='foreign'
    elif fault=='session':v['Labels'][SESSION_LABEL]='foreign'
    elif fault=='operation':v['Labels'][RESTORE_LABEL]='foreign'
    elif fault=='container':c['Id']='replacement'
    elif fault=='volume':c['Mounts'][0]['Name']='foreign'
    elif fault=='image':c['Image']='other'
    elif fault=='mount':c['Mounts'].append({'Type':'bind','Source':'/private','Destination':'/other'})
    elif fault=='network':c['HostConfig']['NetworkMode']='bridge'
    elif fault=='shared':users.append('second')
    else:op['volume_created_at']='different'
    with pytest.raises(StorageError):m.own(op)
    assert not any(a[0] in {'rm','stop'} or a[:2]==('volume','rm') for a in calls)

@pytest.mark.parametrize('fault',['legacy','for_use','pin','lease','unverified'])
def test_restore_protected_never_cleanup(restore_owner,monkeypatch,fault):
    m,op,c,v,u,calls=restore_owner
    monkeypatch.setattr(m,'proof',lambda op:None)
    if fault=='legacy':op['version']='old'
    elif fault=='for_use':op['purpose']='restore_for_use'
    elif fault=='pin':op['pin']='manual keep'
    elif fault=='lease':op['lease']={'owner':'reader'}
    else:op['state']='restoring'
    with pytest.raises(StorageError):m.cleanup(op)
    assert not any(a[0] in {'rm','stop'} or a[:2]==('volume','rm') for a in calls)

@pytest.mark.parametrize('kind',['volume','container'])
@pytest.mark.parametrize('message',['Cannot connect to the Docker daemon','permission denied','timeout','malformed response'])
def test_check_error_is_not_missing(monkeypatch,kind,message):
    from arsia_pipeline import storage_restore
    def failure(*a,**kw):raise subprocess.CalledProcessError(1,'docker',stderr=message.encode())
    monkeypatch.setattr(storage_restore,'docker',failure)
    with pytest.raises(StorageError,match='absence not established'):inspect_optional(kind,'only-recorded')

@pytest.mark.parametrize('kind,message',[('container','Error: No such object: exact'),('volume','Error: No such volume: exact')])
def test_known_absence(monkeypatch,kind,message):
    from arsia_pipeline import storage_restore
    def failure(*a,**kw):raise subprocess.CalledProcessError(1,'docker',stderr=message.encode())
    monkeypatch.setattr(storage_restore,'docker',failure);assert inspect_optional(kind,'exact') is None

def enrolled(space,home):
    cfg=provision(home,uuid4().hex,suite='generic');cfg.update(storage_space=str(space.root),storage_space_id=space.marker['space_id'])
    cfg['storage_policy']['expanded_successes']=space.marker['policy']['expanded_successes']
    s=TestSession(cfg);s.update(retention_family='generic-policy',state='creating',success=True,closed_at='2026-01-01T00:00:00+00:00',baseline={'source':'one'},input_set=['different'])
    atomic_json(s.ledger.root/'runtime.json',cfg);space.register(s,'generic-policy');s.update(state='retained');space.update(s);return s


def test_space_counts_only_exact_runtime_link_without_following_binary(tmp_path, monkeypatch):
    from arsia_pipeline import codex_sandbox
    space=TestSpace.create(tmp_path/'space',reserve_bytes=0)
    session=enrolled(space,space.root/'run/session')
    binary=tmp_path/'codex';binary.write_bytes(b'x'*1000000)
    monkeypatch.setattr(codex_sandbox,'BINARY',binary)
    before=space.measure()['logical_bytes']
    cache=session.ledger.root/'codex-tasks'/str(uuid4())/'home/tmp/arg0/codex-arg0case'
    cache.mkdir(parents=True);link=cache/'apply_patch';link.symlink_to(binary)
    assert space.measure()['logical_bytes']==before+link.lstat().st_size
    space.check_budget(100)
    link.unlink();link.symlink_to(tmp_path/'secret')
    with pytest.raises(StorageError,match='Indirect registered'):space.measure()

@pytest.mark.parametrize('n',[1,2])
def test_catalog_n_cross_run_different_compatibility(tmp_path,monkeypatch,n):
    space=TestSpace.create(tmp_path/'space',expanded_successes=n);ss=[enrolled(space,space.root/('run-'+str(i))/'session') for i in range(3)]
    for i,s in enumerate(ss):s.update(baseline={'source':i},input_set=[str(i)],closed_at='2026-01-01T00:00:0'+str(i)+'+00:00');space.update(s)
    called=[]
    def archive(s):called.append(s.cfg['test_session_id']);s.update(state='archived')
    monkeypatch.setattr(TestSession,'archive_database',archive)
    space.retain(ss[-1]);assert len(called)==3-n
    assert len({r['compatibility'] for r in space.rows()})==3

def test_catalog_pin_claim_and_unknown_history_not_adopted(tmp_path,monkeypatch):
    space=TestSpace.create(tmp_path/'space',expanded_successes=1);ss=[enrolled(space,space.root/('run-'+str(i))/'session') for i in range(3)]
    for i,s in enumerate(ss):s.update(closed_at='2026-01-01T00:00:0'+str(i)+'+00:00');space.update(s)
    space.pin(ss[0].cfg['test_session_id'],'keep first');(space.root/'unknown').mkdir();(space.root/'unknown/session.json').write_text('{}')
    with space.db() as db:db.execute('UPDATE sessions SET claim=?,claim_until=? WHERE id=?',('other-finalizer',9999999999,ss[1].cfg['test_session_id']))
    monkeypatch.setattr(TestSession,'archive_database',lambda s:pytest.fail('must not archive protected/claimed session'))
    results=space.retain(ss[-1]);assert any(r['status']=='deferred' for r in results);assert len(space.rows())==3

@pytest.mark.parametrize('fault',['path','marker','catalog','instance'])
def test_catalog_corruption_fails_closed(tmp_path,fault):
    space=TestSpace.create(tmp_path/'space');s=enrolled(space,space.root/'run/session')
    if fault=='path':
        with space.db() as db:db.execute('UPDATE sessions SET path=?',('/foreign/session',))
    elif fault=='marker':(s.ledger.root/'.storage-owner.json').write_text('{}')
    elif fault=='catalog':(space.root/'space.json').write_text('{}')
    else:
        with space.db() as db:db.execute('UPDATE sessions SET instance=?',('foreign',))
    with pytest.raises((StorageError,ValueError)):TestSpace(space.root).measure()

def test_budget_unknown_and_archive_peak_reserved(tmp_path):
    space=TestSpace.create(tmp_path/'space',budget_bytes=512*1024**2);s=enrolled(space,space.root/'run/session')
    measurement=space.measure();assert measurement['docker_reported_bytes'] is None and measurement['docker_reserved_bytes']>0
    with pytest.raises(StorageError,match='budget'):space.reserve('next',512*1024**2,'new backup peak')
    assert (s.ledger.home/'session.json').exists()
