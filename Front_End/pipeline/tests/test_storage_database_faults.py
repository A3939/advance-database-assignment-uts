"""Explicit fresh PostgreSQL fault matrix; never falls back to the website DB."""
import json
import os
from pathlib import Path
import pytest
from arsia_pipeline.test_session import TestSession
from arsia_pipeline.storage_lifecycle import Ledger,StorageError,atomic_json,plan
from arsia_pipeline.storage_archive import apply,recover,verify

@pytest.fixture(scope='module')
def session():
    home=os.environ.get('ARSIA_STORAGE_FAULT_HOME')
    if not home:pytest.skip('An explicit fresh managed fault-test home is required')
    s=TestSession.create(Path(home),suite='storage-interruption-matrix-v1',postgres_image='efedf3595f1d',
                         executor_image='arsia-import-adapter:closeout-20261002')
    yield s
    atomic_json(s.ledger.home/'storage-finalize.json',s.finish(success=True))

@pytest.mark.parametrize('phase',['intent','partial','verified','evicted_member'])
def test_real_interruption_and_recovery(session,phase):
    p=session.ledger.root/('interruption-'+phase);p.mkdir();(p/'a').write_text('alpha');(p/'b').write_text('beta')
    rid=session.ledger.register('execution_input',str(p.relative_to(session.ledger.root)))
    def hook(current):
        if current==phase:raise KeyboardInterrupt('bounded test interruption')
    with pytest.raises(KeyboardInterrupt):apply(session.cfg,plan(session.cfg)['id'],hook=hook)
    before=session.ledger.get(rid)
    results=recover(session.cfg);answer=next(r for r in results if r['id']==rid)
    if phase in {'verified','evicted_member'}:
        assert answer['status']=='archived' and not p.exists()
        archive=session.ledger.home/'archives'/(before['archive_id']+'.tar.gz')
        assert len(verify(archive)['members'])==3
    else:
        assert answer['status']=='blocked' and (p/'a').read_text()=='alpha' and (p/'b').read_text()=='beta'
        session.ledger.pin(rid,'bounded interruption diagnosis')
    atomic_json(session.ledger.home/('fault-'+phase+'.json'),{'before':before,'recovery':answer})

def test_real_verified_archive_corruption_never_evicts(session):
    p=session.ledger.root/'corruption-source';p.mkdir();(p/'a').write_text('protected original')
    rid=session.ledger.register('execution_input','corruption-source')
    def hook(phase):
        if phase=='verified':raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):apply(session.cfg,plan(session.cfg)['id'],hook=hook)
    record=session.ledger.get(rid);archive=session.ledger.home/'archives'/(record['archive_id']+'.tar.gz')
    archive.write_bytes(archive.read_bytes()[:10])
    result=next(r for r in recover(session.cfg) if r['id']==rid)
    assert result['status']=='blocked' and result['code']=='ARCHIVE_CHANGED'
    assert (p/'a').read_text()=='protected original'
    session.ledger.pin(rid,'corrupt archive diagnosis retained')
    atomic_json(session.ledger.home/'fault-corruption.json',result)

def test_real_budget_block_is_environment_failure(session):
    p=session.ledger.root/'quota-source';p.write_text('no deletion before backup')
    rid=session.ledger.register('execution_input','quota-source');proposal=plan(session.cfg)
    previous=session.cfg['storage_policy']['budget_bytes'];session.cfg['storage_policy']['budget_bytes']=1
    try:result=next(r for r in apply(session.cfg,proposal['id']) if r['id']==rid)
    finally:session.cfg['storage_policy']['budget_bytes']=previous
    assert result['code']=='STORAGE_BUDGET' and p.exists()
    session.ledger.pin(rid,'quota failure evidence retained')
    atomic_json(session.ledger.home/'fault-quota.json',result)
