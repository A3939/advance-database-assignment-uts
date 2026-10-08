import copy,json,os
from pathlib import Path
from uuid import uuid4
import pytest
from arsia_pipeline import trusted_helpers as h,storage_restore
from arsia_pipeline.storage_lifecycle import provision,StorageError
from arsia_pipeline.test_session import TestSession

@pytest.fixture
def identity(tmp_path):
    source=tmp_path/'directory with spaces';source.mkdir();other=tmp_path/'second';other.mkdir()
    daemon={'mapping':'desktop-macos-host-mnt-v1','context':'local','daemon_id':'trusted','endpoint':'unix:///local','server_version':'fixed'}
    cfg=provision(tmp_path/'session',uuid4().hex,suite='helpers');session=TestSession(cfg)
    mounts=[{'type':'bind','source':str(source),'target':'/out','readonly':False},
            {'type':'bind','source':str(other),'target':'/code','readonly':True},
            {'type':'volume','source':'exact-volume','target':'/data','readonly':True}]
    intent={'version':h.VERSION,'name':'only-this-helper','helper_id':uuid4().hex,'operation_id':uuid4().hex,
        'session_id':cfg['test_session_id'],'instance_id':cfg['instance_id'],'image':'sha256:exact','caps':['DAC_OVERRIDE'],
        'mounts':mounts,'host_paths':{m['source']:h.host_path_identity(m['source']) for m in mounts if m['type']=='bind'},'daemon':daemon}
    actual={'Id':'a'*64,'Name':'/'+intent['name'],'Image':intent['image'],
        'Config':{'User':'0:0','Labels':{'arsia.storage.session':intent['session_id'],'arsia.storage.instance':intent['instance_id'],h.HELPER_LABEL:intent['helper_id'],h.OPERATION_LABEL:intent['operation_id']}},
        'HostConfig':{'NetworkMode':'none','ReadonlyRootfs':True,'Privileged':False,'CapDrop':['ALL'],'CapAdd':['CAP_DAC_OVERRIDE']},
        'State':{'Running':True,'Status':'running','ExitCode':0},
        'Mounts':[{'Type':m['type'],'Source':'/host_mnt'+m['source'] if m['type']=='bind' else '/daemon/volume','Name':m['source'] if m['type']=='volume' else None,'Destination':m['target'],'RW':not m['readonly']} for m in mounts]}
    return session,intent,actual,daemon

def persist(s,i,a,d):
    receipt=h.validate(i,a,d,container_id=a['Id'])
    s.ledger.journal('helper_intent',**i)
    s.ledger.journal('helper_created',helper_id=i['helper_id'],container_id=a['Id'])
    s.ledger.journal('helper_receipt',helper_id=i['helper_id'],receipt=receipt,sha256=h.digest(receipt))
    return receipt

@pytest.mark.parametrize('translated',[False,True])
def test_direct_and_exact_desktop_mixed_mounts(identity,translated):
    s,i,a,d=identity
    if not translated:
        for m in a['Mounts']:
            if m['Type']=='bind':m['Source']=m['Source'].removeprefix('/host_mnt')
    receipt=persist(s,i,a,d)
    assert len(receipt['mapping'])==3
    assert h.validate(i,a,d,container_id=a['Id'],receipt=receipt)==receipt

@pytest.mark.parametrize('fault',['similar-prefix','different-directory','double-prefix','traversal','target','type','rw','count','volume','image','session','instance','operation','nonce','id','name','network','privileged','readonly','user','capability','daemon','unconfirmed-mapping'])
def test_bad_initial_mount_or_identity_never_admitted(identity,fault):
    s,i,a,d=identity;a=copy.deepcopy(a);d=copy.deepcopy(d)
    if fault=='similar-prefix':a['Mounts'][0]['Source']+='-other'
    elif fault=='different-directory':a['Mounts'][0]['Source']=a['Mounts'][1]['Source']
    elif fault=='double-prefix':a['Mounts'][0]['Source']='/host_mnt'+a['Mounts'][0]['Source']
    elif fault=='traversal':a['Mounts'][0]['Source']+='/../directory with spaces'
    elif fault=='target':a['Mounts'][0]['Destination']='/else'
    elif fault=='type':a['Mounts'][0]['Type']='volume'
    elif fault=='rw':a['Mounts'][0]['RW']=False
    elif fault=='count':a['Mounts'].pop()
    elif fault=='volume':a['Mounts'][2]['Name']='different-volume'
    elif fault=='image':a['Image']='sha256:other'
    elif fault in {'session','instance','operation','nonce'}:
        key={'session':'arsia.storage.session','instance':'arsia.storage.instance','operation':h.OPERATION_LABEL,'nonce':h.HELPER_LABEL}[fault];a['Config']['Labels'][key]='other'
    elif fault=='id':a['Id']='b'*64
    elif fault=='name':a['Name']='/replaced'
    elif fault=='network':a['HostConfig']['NetworkMode']='bridge'
    elif fault=='privileged':a['HostConfig']['Privileged']=True
    elif fault=='readonly':a['HostConfig']['ReadonlyRootfs']=False
    elif fault=='user':a['Config']['User']='1000'
    elif fault=='capability':a['HostConfig']['CapAdd'].append('CAP_SYS_ADMIN')
    elif fault=='daemon':d['daemon_id']='replacement'
    else:d['mapping']='unknown';i['daemon']=copy.deepcopy(d)
    with pytest.raises(StorageError):h.validate(i,a,d,container_id='a'*64)
    assert h.records(s)==[]

@pytest.mark.parametrize('fault',['symlink','replaced-directory','dotdot'])
def test_host_path_identity_changes_rejected(identity,fault):
    s,i,a,d=identity;p=Path(i['mounts'][0]['source'])
    if fault=='dotdot':
        with pytest.raises(StorageError):h.host_path_identity(str(p)+'/../'+p.name)
        return
    old=p.with_name('old');p.rename(old)
    if fault=='symlink':p.symlink_to(old,target_is_directory=True)
    else:p.mkdir()
    with pytest.raises(StorageError):h.validate(i,a,d,container_id=a['Id'])


def recovery_environment(monkeypatch,s,i,a,d):
    pool={a['Id']:a};actions=[]
    def inspect(kind,key):return pool.get(a['Id']) if key in {a['Id'],i['name']} else None
    def docker(*args,**kw):
        actions.append(args)
        assert args[-1]==a['Id']
        if args[0]=='stop':a['State']['Running']=False
        elif args[0]=='rm':pool.clear()
        else:raise AssertionError(args)
    monkeypatch.setattr(storage_restore,'inspect_optional',inspect)
    monkeypatch.setattr(h,'daemon_identity',lambda call:d)
    return pool,actions,docker


def test_fresh_session_persistent_receipt_recovery_idempotent(identity,monkeypatch):
    s,i,a,d=identity;persist(s,i,a,d);pool,actions,docker=recovery_environment(monkeypatch,s,i,a,d)
    h.recover(TestSession(s.cfg),docker);h.recover(TestSession(s.cfg),docker)
    assert actions==[('stop','--time','5',a['Id']),('rm',a['Id'])]
    assert not pool

@pytest.mark.parametrize('fault',['missing','corrupt','torn','replacement','wrong-mount','daemon','legacy','no-created-id'])
def test_recovery_refuses_uncertain_without_mutation(identity,monkeypatch,fault):
    s,i,a,d=identity
    if fault in {'missing','torn','no-created-id'}:
        s.ledger.journal('helper_intent',**i)
        if fault!='no-created-id':s.ledger.journal('helper_created',helper_id=i['helper_id'],container_id=a['Id'])
        if fault=='torn':s.ledger.journal('helper_receipt',helper_id=i['helper_id'],receipt={'incomplete':True},sha256='wrong')
    elif fault=='legacy':s.ledger.journal('helper_intent',name=i['name'],session_id=i['session_id'],mounts=i['mounts'],image=i['image'])
    else:persist(s,i,a,d)
    pool,actions,docker=recovery_environment(monkeypatch,s,i,a,d)
    if fault=='corrupt':
        with s.ledger.connect() as db:db.execute("UPDATE journal SET details=? WHERE event='helper_receipt'",(json.dumps({'helper_id':i['helper_id'],'receipt':{},'sha256':'invalid'}),))
    if fault=='replacement':
        pool.clear();a['Id']='b'*64;pool[a['Id']]=a
    if fault=='wrong-mount':a['Mounts'][0]['Source']+='-wrong'
    if fault=='daemon':d=dict(d,daemon_id='remote');monkeypatch.setattr(h,'daemon_identity',lambda call:d)
    with pytest.raises(StorageError):h.recover(TestSession(s.cfg),docker)
    assert not actions

@pytest.mark.parametrize('override',['DOCKER_HOST','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'])
def test_remote_override_refused(monkeypatch,override):
    monkeypatch.setenv(override,'remote')
    with pytest.raises(StorageError):h.daemon_identity(lambda *a:pytest.fail('no daemon access'))
