import json
from pathlib import Path
import pytest

from arsia_pipeline.storage_lifecycle import (Ledger, StorageError, provision,
    validate_managed, bounded_path, reasons, PROTECTED, assert_budget)
from arsia_pipeline.storage_archive import create, verify, restore, evict, inventory


@pytest.fixture
def managed(tmp_path):
    cfg=provision(tmp_path/'session','instance-one',suite='synthetic-unit',budget_bytes=32*1024**2)
    cfg['storage_policy']['reserve_bytes']=0
    return cfg,Ledger(cfg)


@pytest.mark.parametrize('fault',['instance','session','purpose','root','marker','policy','symlink'])
def test_owner_refuses_changes(managed,tmp_path,fault):
    cfg,ledger=managed;changed=json.loads(json.dumps(cfg))
    if fault=='instance':changed['instance_id']='other'
    elif fault=='session':changed['test_session_id']='other'
    elif fault=='purpose':changed['purpose']='local-test'
    elif fault=='root':changed['data_root']=str(tmp_path/'another')
    elif fault=='marker':(ledger.root/'.storage-owner.json').unlink()
    elif fault=='policy':changed['storage_policy']['version']='unknown'
    elif fault=='symlink':
        p=ledger.root/'.storage-owner.json';p.rename(ledger.home/'marker');p.symlink_to(ledger.home/'marker')
    with pytest.raises(StorageError):validate_managed(changed)


@pytest.mark.parametrize('status',sorted(PROTECTED))
def test_recoverable_states_protect(managed,status):
    cfg,ledger=managed;(ledger.root/'scratch').write_text('work')
    rid=ledger.register('execution_input','scratch')
    assert 'active or recoverable jobs' in reasons(ledger.get(rid),{'active':[{'status':status}],'references':[]},ledger.root)


@pytest.mark.parametrize('origin',['releases.sources','batches.result','adapter_versions.code_path','agent_sessions.checkpoint','agent_steps.evidence_path','jobs.result'])
def test_reference_and_pin(managed,origin):
    cfg,ledger=managed;(ledger.root/'scratch').write_text('work')
    rid=ledger.register('execution_input','scratch')
    snapshot={'active':[],'references':[{'path':str(ledger.root/'scratch'),'reason':origin}]}
    assert reasons(ledger.get(rid),snapshot,ledger.root)==['referenced by '+origin]
    ledger.pin(rid,'retain diagnostic')
    assert 'pin: retain diagnostic' in reasons(ledger.get(rid),snapshot,ledger.root)
    ledger.pin(rid,None)
    assert reasons(ledger.get(rid),{'active':[],'references':[]},ledger.root)==[]


def tree(tmp_path):
    root=tmp_path/'source';root.mkdir()
    (root/'nested').mkdir();(root/'nested/a.txt').write_bytes(b'evidence'*100)
    (root/'b.bin').write_bytes(bytes(range(256)))
    return root


def test_full_archive_restore_and_never_overwrite(tmp_path):
    root=tree(tmp_path);before=inventory(root);archive=tmp_path/'archive.tar.gz'
    manifest=create(root,archive)
    assert verify(archive)==manifest
    target=tmp_path/'restored';restore(archive,target)
    observed=inventory(target)
    for a,b in zip(before,observed):
        assert {k:v for k,v in a.items() if k not in {'uid','gid'}}=={k:v for k,v in b.items() if k not in {'uid','gid'}}
    with pytest.raises(StorageError,match='new'):restore(archive,target)


@pytest.mark.parametrize('fault',['corrupt','source_changed','symlink','hardlink','no_space'])
def test_archive_faults_never_delete(tmp_path,managed,fault):
    root=tree(tmp_path);archive=tmp_path/'archive.tar.gz'
    if fault=='symlink':(root/'link').symlink_to(tmp_path)
    if fault=='hardlink':
        import os
        os.link(root/'b.bin',root/'same.bin')
    if fault in {'symlink','hardlink'}:
        with pytest.raises(StorageError):create(root,archive)
    elif fault=='source_changed':
        def hook(stage):
            if stage=='written':(root/'b.bin').write_bytes(b'changed')
        with pytest.raises(StorageError,match='changed'):create(root,archive,hook=hook)
    elif fault=='corrupt':
        create(root,archive);data=archive.read_bytes();archive.write_bytes(data[:len(data)//2])
        with pytest.raises(StorageError):verify(archive)
    else:
        cfg,ledger=managed;cfg['storage_policy']['budget_bytes']=1
        with pytest.raises(StorageError,match='budget'):assert_budget(ledger,1024)
    assert (root/'nested/a.txt').is_file()


def test_runtime_argv_cache_does_not_block_next_job_budget_or_grant_file_access(managed, tmp_path, monkeypatch):
    from uuid import uuid4
    from arsia_pipeline import codex_sandbox
    cfg, ledger = managed
    binary = tmp_path/'reviewed-codex'; binary.write_bytes(b'fixture-runtime')
    monkeypatch.setattr(codex_sandbox, 'BINARY', binary)
    cache = ledger.root/'codex-tasks'/str(uuid4())/'home/tmp/arg0/codex-arg0fixture'
    cache.mkdir(parents=True)
    link = cache/'apply_patch'; link.symlink_to(binary)
    assert_budget(ledger, 1024)
    # Accounting tolerance does not allow reading or archiving indirect data.
    with pytest.raises(StorageError): bounded_path(ledger.root, link.relative_to(ledger.root), exists=True)
    with pytest.raises(StorageError): inventory(cache)
    link.unlink(); link.symlink_to(tmp_path/'private-credentials')
    with pytest.raises(StorageError, match='Indirect session'): assert_budget(ledger)


@pytest.mark.parametrize('relative', ['attempts/job/apply_patch', 'blobs/sha256/apply_patch',
    'codex-tasks/not-a-job/home/tmp/arg0/codex-arg0fixture/apply_patch',
    'codex-tasks/00000000-0000-0000-0000-000000000001/home/tmp/arg0/other/apply_patch'])
def test_runtime_cache_exception_does_not_expand_to_other_paths(managed, tmp_path, monkeypatch, relative):
    from arsia_pipeline import codex_sandbox
    cfg, ledger = managed
    binary = tmp_path/'reviewed-codex'; binary.write_bytes(b'fixture')
    monkeypatch.setattr(codex_sandbox, 'BINARY', binary)
    link = ledger.root/relative; link.parent.mkdir(parents=True); link.symlink_to(binary)
    with pytest.raises(StorageError, match='Indirect session'): assert_budget(ledger)


@pytest.mark.parametrize('stop',['partial','written','published'])
def test_archive_interruption_keeps_source(tmp_path,stop):
    root=tree(tmp_path);archive=tmp_path/'archive.tar.gz';before=inventory(root)
    def hook(phase):
        if phase==stop:raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):create(root,archive,hook=hook)
    assert inventory(root)==before
    if stop=='published':assert verify(archive)['members']==before
    else:assert not archive.exists()


def test_partial_eviction_is_resumable(tmp_path):
    root=tree(tmp_path);archive=tmp_path/'archive.tar.gz';manifest=create(root,archive)
    def hook(phase):raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):evict(root,manifest,hook=hook)
    evict(root,verify(archive));assert not root.exists()
    restore(archive,tmp_path/'restored');assert (tmp_path/'restored/nested/a.txt').read_bytes()==b'evidence'*100


def test_eviction_refuses_new_member(tmp_path):
    root=tree(tmp_path);manifest=create(root,tmp_path/'a.tar.gz')
    (root/'new').write_text('new referenced data')
    with pytest.raises(StorageError,match='changed'):evict(root,manifest)
    assert (root/'new').exists() and (root/'b.bin').exists()


def test_ledger_lock_conflict_and_no_paths_in_browser(managed):
    cfg,ledger=managed;(ledger.root/'scratch').write_text('work');ledger.register('execution_input','scratch')
    with ledger.lock():
        with pytest.raises(StorageError,match='active'): 
            with Ledger(cfg).lock():pass
    value=json.dumps(ledger.snapshot())
    assert str(ledger.root) not in value and 'dsn' not in value
    assert ledger.snapshot()['docker_bytes'] is None


def test_no_path_escape_or_indirect_parent(managed,tmp_path):
    cfg,ledger=managed
    with pytest.raises(StorageError):bounded_path(ledger.root,'../outside')
    (ledger.root/'indirect').symlink_to(tmp_path)
    with pytest.raises(StorageError):bounded_path(ledger.root,'indirect/payload')


def test_system_storage_error_never_requests_adapter_revision():
    from arsia_pipeline.capability_preflight import classified_blockers, execution_blockers
    row=classified_blockers(StorageError('STORAGE_SPACE','disk reserve'))[0]
    assert row['responsible_party']=='system' and row['kind']=='environment_dependency'
    run={'status':'failed','run_id':'test','error':{'type':'StorageError','origin':'trusted_host',
        'kind':'environment_dependency','code':'STORAGE_SPACE','message':'disk reserve'}}
    row=execution_blockers(run,operation='run_adapter')[0]
    assert row['responsible_party']=='system' and row['kind']=='environment_dependency'


def test_legacy_agent_stops_on_storage_error(monkeypatch):
    from arsia_pipeline.agent import AgentSession
    from arsia_pipeline.errors import NeedsInput
    session=object.__new__(AgentSession);session.adaptation_v1=False
    def fail(*a,**k):raise StorageError('STORAGE_BUDGET','quota reached')
    monkeypatch.setattr(session,'_execute_tool',fail)
    with pytest.raises(NeedsInput) as exc:session.execute_tool('run_adapter',{})
    assert exc.value.questions==[] and exc.value.details['blockers'][0]['responsible_party']=='system'
