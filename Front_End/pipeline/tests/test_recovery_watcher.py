"""Dry-run and guard tests; never interrupt a worker or query a database."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'tools'/'watch_owned_agent_recovery.py'
    spec=importlib.util.spec_from_file_location('owned_watcher_test',path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def test_default_is_dry_description_without_environment_calls(monkeypatch,capsys):
    value=module()
    monkeypatch.setattr(value.sys,'argv',['watch_owned_agent_recovery.py'])
    monkeypatch.setattr(value,'read_config',lambda:pytest.fail('Dry run must not read runtime'))
    monkeypatch.setattr(value,'docker',lambda *a:pytest.fail('Dry run must not call Docker'))
    monkeypatch.setattr(value.os,'kill',lambda *a:pytest.fail('Dry run must not signal a process'))
    value.main()
    assert '"dry_run": true' in capsys.readouterr().out


def test_other_active_job_prevents_any_sandbox_or_process_action(monkeypatch):
    value=module()
    monkeypatch.setattr(value,'snapshot',lambda *a:({'attempt':2,'status':'processing'},None,None,None,[{'id':'other'}]))
    monkeypatch.setattr(value,'docker',lambda *a:pytest.fail('Foreign job must block before Docker inspection'))
    with pytest.raises(RuntimeError,match='Another queued/active job'):
        value.wait_trigger({},value.time.monotonic()+1)


def test_completed_or_later_attempt_cannot_be_interrupted(monkeypatch):
    value=module()
    monkeypatch.setattr(value,'snapshot',lambda *a:({'attempt':3,'status':'processing'},None,None,None,[]))
    monkeypatch.setattr(value,'docker',lambda *a:pytest.fail('Wrong attempt must block before Docker inspection'))
    with pytest.raises(RuntimeError,match='designated attempt ended'):
        value.wait_trigger({},value.time.monotonic()+1)


def test_multiple_owned_containers_refuse_injection(monkeypatch):
    value=module()
    monkeypatch.setattr(value,'snapshot',lambda *a:({'attempt':2,'status':'processing'},None,{'active_job_id':value.TARGET},None,[]))
    calls=[]
    def docker(args):
        calls.append(args)
        return SimpleNamespace(returncode=0,stdout='a'*64+'\n'+'b'*64)
    monkeypatch.setattr(value,'docker',docker)
    with pytest.raises(RuntimeError,match='Multiple designated running sandboxes'):
        value.wait_trigger({'instance_id':'test-instance'},value.time.monotonic()+1)
    assert len(calls)==1 and 'label=arsia.import.job='+value.TARGET in calls[0]


def test_uninjected_controlled_hold_is_released_by_exact_id(monkeypatch):
    value=module();calls=[];container_id='a'*64
    monkeypatch.setattr(value,'docker',lambda args:(calls.append(args) or SimpleNamespace(returncode=0)))
    receipt={'injected':False}
    value.release_uninjected_hold(receipt,container_id)
    assert calls==[['unpause',container_id]]
    assert receipt['controlled_hold_release']['returncode']==0


def test_injected_orphan_belongs_to_startup_reaper_not_watcher(monkeypatch):
    value=module()
    monkeypatch.setattr(value,'docker',lambda *a:pytest.fail('Injected orphan must be handled by the trusted reaper'))
    value.release_uninjected_hold({'injected':True},'a'*64)
    value.release_uninjected_hold({'injected':False},None)


def test_hold_release_failure_is_audited_without_erasing_original_failure(monkeypatch):
    value=module()
    def fail(*args):raise TimeoutError('unpause unavailable')
    monkeypatch.setattr(value,'docker',fail)
    receipt={'injected':False,'error':'original ownership conflict'}
    value.release_uninjected_hold(receipt,'a'*64)
    assert receipt['error']=='original ownership conflict'
    assert receipt['controlled_hold_release']['requires_scoped_operator_review'] is True


def test_unknown_pause_result_still_releases_exact_proven_container(monkeypatch,tmp_path):
    value=module();calls=[];saved=[];container_id='c'*64
    monkeypatch.setattr(value,'ROOT',tmp_path)
    monkeypatch.setattr(value.sys,'argv',['watch_owned_agent_recovery.py',
        '--confirm-owned-agent-interruption','--hold-owned-container'])
    monkeypatch.setattr(value,'read_config',lambda:{})
    monkeypatch.setattr(value,'private_json',lambda path,receipt,**kw:saved.append(dict(receipt)))
    session={'id':'session','model_calls':1,'tool_calls':1,'correction_count':0,'checkpoint':{}}
    owned={'container_id':container_id,'run_id':'run','ownership_sha256':'proof'}
    monkeypatch.setattr(value,'wait_trigger',lambda *a:(owned,123,'started',{},session,None))
    def docker(args):
        calls.append(args)
        if args[0]=='pause':raise TimeoutError('Docker may already have paused')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(value,'docker',docker)
    monkeypatch.setattr(value.os,'kill',lambda *a:pytest.fail('No signal after an uncertain pause'))
    with pytest.raises(TimeoutError,match='already have paused'):
        value.main()
    assert calls==[['pause',container_id],['unpause',container_id]]
    assert saved[-1]['injected'] is False
    assert saved[-1]['controlled_hold_release']['returncode']==0


@pytest.mark.parametrize('state,requires_review',[
    ('paused',True),('running',False),('removed',False),('unreachable',True),
])
def test_nonzero_unpause_requires_exact_state_verification(monkeypatch,state,requires_review):
    value=module();calls=[];container_id='d'*64
    def docker(args):
        calls.append(args)
        if args[0]=='unpause':return SimpleNamespace(returncode=1)
        if state in {'paused','running'}:
            return SimpleNamespace(returncode=0,stdout=value.json.dumps([
                {'Id':container_id,'State':{'Paused':state=='paused'}}]))
        return SimpleNamespace(returncode=1,stderr=(
            'Error: No such object: '+container_id if state=='removed' else 'Cannot connect to Docker'))
    monkeypatch.setattr(value,'docker',docker)
    receipt={'injected':False}
    value.release_uninjected_hold(receipt,container_id)
    assert calls==[['unpause',container_id],['inspect',container_id]]
    assert receipt['controlled_hold_release']['requires_scoped_operator_review'] is requires_review
