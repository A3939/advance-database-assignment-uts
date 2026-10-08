"""Offline recovery ownership tests: never call Docker or signal a process."""
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from arsia_pipeline import scoped_orphans as orphan


class Connection:
    def __init__(self,config,attempt,locked=True):
        self.config,self.attempt,self.locked = config,attempt,locked
    def execute(self,sql,args=None):
        if 'local_instance' in sql: row={'instance_id':self.config['instance_id']}
        elif 'pg_locks' in sql: row={'locked':self.locked}
        elif 'FROM attempts' in sql:
            row=self.attempt if self.attempt and args==(self.attempt['id'],self.attempt['job_id']) else None
        else: raise AssertionError(sql)
        return SimpleNamespace(fetchone=lambda:row)


class Docker:
    def __init__(self,containers,fail_remove=False):
        self.containers={value['Id']:value for value in containers}
        self.calls,self.fail_remove=[],fail_remove
    def __call__(self,args):
        self.calls.append(args)
        if args[0]=='ps': return SimpleNamespace(returncode=0,stdout='\n'.join(self.containers))
        if args[0]=='inspect':
            value=self.containers.get(args[1])
            return SimpleNamespace(returncode=0 if value else 1,stdout=json.dumps([value]) if value else '')
        if args[:2]==['rm','-f']:
            if self.fail_remove: return SimpleNamespace(returncode=1,stdout='')
            self.containers.pop(args[2])
            return SimpleNamespace(returncode=0,stdout=args[2])
        raise AssertionError(args)


def fixture(tmp_path):
    config={'data_root':str(tmp_path),'instance_id':'owned-instance'}
    job,attempt,run = str(uuid4()),str(uuid4()),uuid4().hex
    work=tmp_path/'attempts'/job/attempt
    folder=work/'agent'/('run-'+run)
    (folder/'input').mkdir(parents=True)
    (folder/'output').mkdir()
    (folder/'input'/'adapter.py').write_text('def adapt(ctx): pass')
    receipt=orphan.write_ownership(folder,config=config,job_id=job,attempt_id=attempt)
    info={'Id':'a'*64,'Name':'/'+receipt['container_name'],'Config':{'Labels':orphan.ownership_labels(receipt)},
          'State':{'Running':True},'Mounts':[{'Type':'bind','Source':str(folder/'input'),'Destination':'/input','RW':False},
                                          {'Type':'bind','Source':str(folder/'output'),'Destination':'/output','RW':True}]}
    conn=Connection(config,{'id':attempt,'job_id':job,'work_dir':str(work),'status':'running'})
    return config,conn,folder,receipt,info


def test_valid_incomplete_owned_run_is_removed_by_full_id_and_audited(tmp_path):
    config,conn,folder,receipt,info=fixture(tmp_path)
    docker=Docker([info])
    result=orphan.recover_owned_orphans(conn,config,docker)
    assert result['status']=='passed' and result['actions'][0]['status']=='removed'
    assert ['rm','-f','a'*64] in docker.calls
    assert not docker.containers
    assert (folder/'input'/'adapter.py').is_file()
    assert json.loads((folder/'orphan-recovery.json').read_text())['run_id']==receipt['run_id']
    assert (folder/'ownership.json').stat().st_mode & 0o777 == 0o600
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in (tmp_path/'audits').glob('*.json'))


@pytest.mark.parametrize('change',['instance_label','job_label','attempt_label','run_label','receipt_hash','mount_rw','extra_bind','db_attempt','db_path','receipt_missing','receipt_mode','receipt_tamper','completed_running','execution_symlink'])
def test_ambiguous_local_container_blocks_without_deleting(tmp_path,change):
    config,conn,folder,receipt,info=fixture(tmp_path)
    if change in {'instance_label','job_label','attempt_label','run_label'}:
        key=change.removesuffix('_label')
        info['Config']['Labels'][orphan.PREFIX+key]='wrong'
    elif change=='receipt_hash': info['Config']['Labels'][orphan.PREFIX+'owner-sha256']='0'*64
    elif change=='mount_rw': info['Mounts'][0]['RW']=True
    elif change=='extra_bind': info['Mounts'].append({'Type':'bind','Source':'/unrelated','Destination':'/extra','RW':True})
    elif change=='db_attempt': conn.attempt=None
    elif change=='db_path': conn.attempt['work_dir']=str(tmp_path/'other')
    elif change=='receipt_missing': (folder/'ownership.json').unlink()
    elif change=='receipt_mode': (folder/'ownership.json').chmod(0o644)
    elif change=='receipt_tamper':
        receipt['worker_pid']+=1
        (folder/'ownership.json').write_text(json.dumps(receipt))
    elif change=='completed_running': (folder/'execution.json').write_text(json.dumps({'status':'succeeded'}))
    elif change=='execution_symlink': (folder/'execution.json').symlink_to(tmp_path/'missing.json')
    docker=Docker([info])
    with pytest.raises(orphan.OrphanRecoveryBlocked): orphan.recover_owned_orphans(conn,config,docker)
    assert not any(call[0]=='rm' for call in docker.calls)
    assert list((tmp_path/'audits').glob('*.json'))
    assert all(json.loads(path.read_text())['status']=='blocked' for path in (tmp_path/'audits').glob('*.json'))


def test_foreign_project_generic_adapter_label_is_ignored(tmp_path):
    config,conn,folder,receipt,info=fixture(tmp_path)
    info['Mounts'][0]['Source']='/another/project/run/input'
    info['Mounts'][1]['Source']='/another/project/run/output'
    info['Config']['Labels']={orphan.PREFIX+'adapter':receipt['container_name']}
    docker=Docker([info])
    result=orphan.recover_owned_orphans(conn,config,docker)
    assert result['status']=='passed' and not result['actions']
    assert not any(call[0]=='rm' for call in docker.calls)


def test_recovery_refuses_without_global_session_lock_before_docker_inventory(tmp_path):
    config,conn,folder,receipt,info=fixture(tmp_path)
    conn.locked=False
    docker=Docker([info])
    with pytest.raises(orphan.OrphanRecoveryBlocked,match='session lock'):
        orphan.recover_owned_orphans(conn,config,docker)
    assert not docker.calls


def test_cleanup_failure_is_audited_and_blocks_new_work(tmp_path):
    config,conn,folder,receipt,info=fixture(tmp_path)
    docker=Docker([info],fail_remove=True)
    with pytest.raises(orphan.OrphanRecoveryBlocked,match='cleanup failed'):
        orphan.recover_owned_orphans(conn,config,docker)
    audit=json.loads(next((tmp_path/'audits').glob('*.json')).read_text())
    assert audit['status']=='blocked' and audit['actions'][0]['status']=='removal_failed'


def test_completed_stopped_container_is_not_incomplete_recovery(tmp_path):
    config,conn,folder,receipt,info=fixture(tmp_path)
    info['State']['Running']=False
    (folder/'execution.json').write_text(json.dumps({'status':'succeeded'}))
    docker=Docker([info])
    assert orphan.recover_owned_orphans(conn,config,docker)['actions']==[]
    assert not any(call[0]=='rm' for call in docker.calls)


def test_receipt_creation_rejects_other_attempt_path_and_overwrite(tmp_path):
    config,conn,folder,receipt,info=fixture(tmp_path)
    with pytest.raises(orphan.OrphanRecoveryBlocked):
        orphan.write_ownership(folder,config=config,job_id=uuid4(),attempt_id=receipt['attempt_id'])
    with pytest.raises(FileExistsError):
        orphan.write_ownership(folder,config=config,job_id=receipt['job_id'],attempt_id=receipt['attempt_id'])


def test_other_marked_database_in_same_root_is_not_removed_or_blocked(tmp_path):
    config,conn,folder,receipt,info=fixture(tmp_path)
    conn.attempt=None
    info['Config']['Labels'][orphan.PREFIX+'instance']='other-test-instance'
    docker=Docker([info])
    assert orphan.recover_owned_orphans(conn,config,docker)['actions']==[]
    assert not any(call[0]=='rm' for call in docker.calls)


def test_executor_arguments_bind_receipt_labels_without_mounting_receipt(tmp_path):
    from arsia_pipeline.isolated_executor import arguments,DEFAULT_LIMITS
    config,conn,folder,receipt,info=fixture(tmp_path)
    args=arguments(receipt['container_name'],folder/'input',folder/'output','sha256:'+'b'*64,DEFAULT_LIMITS,receipt)
    for key,value in orphan.ownership_labels(receipt).items():
        assert key+'='+value in args
    assert 'ownership.json' not in ' '.join(str(item) for item in args)
    assert args[-1]=='sha256:'+'b'*64
