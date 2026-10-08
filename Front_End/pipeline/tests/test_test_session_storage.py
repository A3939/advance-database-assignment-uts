import json
from pathlib import Path
import pytest
from arsia_pipeline.storage_lifecycle import Ledger, StorageError, provision, atomic_json
from arsia_pipeline.test_session import TestSession, SESSION_LABEL, INSTANCE_LABEL


@pytest.fixture
def owner(tmp_path,monkeypatch):
    cfg=provision(tmp_path/'session','instance',suite='ownership-unit')
    cfg['database']='arsia_imports_storage'
    session=TestSession(cfg)
    owned={'name':'exact-test','volume':'exact-volume','image':'sha256:postgres',
           'executor_image':'sha256:executor','container_id':'abcdef1234567890'}
    session.update(docker=owned,state='retained')
    labels={SESSION_LABEL:cfg['test_session_id'],INSTANCE_LABEL:cfg['instance_id']}
    actual={'Id':owned['container_id'],'Name':'/exact-test','Image':'sha256:postgres',
            'Config':{'Labels':labels.copy()},'State':{'Running':False,'ExitCode':0},
            'Mounts':[{'Type':'volume','Name':'exact-volume','Destination':'/var/lib/postgresql/data','RW':True}]}
    volume={'Name':'exact-volume','Labels':labels.copy()}
    users=['abcdef123456']
    from arsia_pipeline import test_session
    def docker(*args,**kwargs):
        if args[0]=='inspect':return json.dumps([actual]).encode()
        if args[:2]==('volume','inspect'):return json.dumps([volume]).encode()
        if args[0]=='ps':return '\n'.join(users).encode()
        raise AssertionError('Unexpected mutation '+str(args))
    monkeypatch.setattr(test_session,'docker',docker)
    return session,actual,volume,users


def test_exact_exclusive_owner_accepted(owner):
    session,*_=owner;assert session.own()[0]['name']=='exact-test'


@pytest.mark.parametrize('fault',['wrong_instance','wrong_session','replaced_container','image','foreign_volume','extra_mount','shared_container'])
def test_external_owner_boundaries_refuse(owner,fault):
    s,c,v,users=owner
    if fault=='wrong_instance':c['Config']['Labels'][INSTANCE_LABEL]='other'
    elif fault=='wrong_session':c['Config']['Labels'][SESSION_LABEL]='other'
    elif fault=='replaced_container':c['Id']='new-id'
    elif fault=='image':c['Image']='sha256:different'
    elif fault=='foreign_volume':v['Labels'][SESSION_LABEL]='other'
    elif fault=='extra_mount':c['Mounts'].append({'Type':'bind','Source':'/external','Destination':'/tablespace','RW':True})
    else:users.append('another-container')
    with pytest.raises(StorageError):s.own()


def test_unclean_database_not_archived(owner):
    s,c,v,_=owner;c['State']['ExitCode']=137
    with pytest.raises(StorageError,match='normally'):s.archive_database()


def test_running_database_not_archived(owner):
    s,c,v,_=owner;c['State']['Running']=True
    with pytest.raises(StorageError,match='normally'):s.archive_database()


def test_shared_child_database_not_archived(owner):
    s,*_=owner
    atomic_json(s.ledger.home/'database-before-stop.json',{'databases':['postgres','arsia_imports_storage','arsia_imports_child']})
    with pytest.raises(StorageError,match='Multiple'):s.archive_database()


def test_status_does_not_write_ledger(owner):
    s,*_=owner
    before=s.ledger.path.stat().st_mtime_ns
    Ledger(s.cfg,read_only=True).snapshot()
    assert s.ledger.path.stat().st_mtime_ns==before
