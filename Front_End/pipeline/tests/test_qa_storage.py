import json
import sqlite3
from pathlib import Path
import pytest
from arsia_pipeline.storage_lifecycle import Ledger, provision, atomic_json
from arsia_pipeline import qa_storage


@pytest.fixture
def managed(tmp_path,monkeypatch):
    cfg=provision(tmp_path/'session','instance',suite='qa-tests')
    from arsia_pipeline import config
    monkeypatch.setattr(config,'read_config',lambda:cfg)
    return cfg,Ledger(cfg)


def work(ledger):
    dbpath=ledger.root/'qa.sqlite';db=sqlite3.connect(dbpath)
    token=qa_storage.begin(ledger.root,dbpath,{'run_id':'test'})
    db.execute('CREATE TABLE work(id integer)');db.close()
    return dbpath,token


def test_success_result_persisted_before_scratch_removed(managed):
    cfg,ledger=managed;path,token=work(ledger);result=ledger.root/'qa.json'
    atomic_json(result,{'admission':'sample_only'})
    qa_storage.finish(token,result_path=result)
    assert not path.exists() and json.loads(result.read_text())['admission']=='sample_only'
    assert ledger.get(token[1])['state']=='reclaimed'


def test_failure_and_interruption_preserve_diagnosis(managed):
    cfg,ledger=managed;path,token=work(ledger)
    qa_storage.finish(token,error=KeyboardInterrupt())
    assert path.exists() and path.with_suffix('.diagnostic.json').exists()
    assert ledger.get(token[1])['state']=='retained'


def test_no_result_no_reclamation(managed):
    cfg,ledger=managed;path,token=work(ledger)
    qa_storage.finish(token)
    assert path.exists() and ledger.get(token[1])['state']=='blocked'


def test_symlink_sidecar_prevents_cleanup(managed,tmp_path):
    cfg,ledger=managed;path,token=work(ledger);result=ledger.root/'qa.json';atomic_json(result,{})
    external=tmp_path/'external';external.write_text('protected')
    Path(str(path)+'-wal').symlink_to(external)
    qa_storage.finish(token,result_path=result)
    assert path.exists() and external.read_text()=='protected'


def test_legacy_configuration_preserves_workfiles(tmp_path,monkeypatch):
    from arsia_pipeline import config
    monkeypatch.setattr(config,'read_config',lambda:{'mode':'local-test'})
    path=tmp_path/'work.sqlite';path.touch()
    assert qa_storage.begin(tmp_path,path,{'run_id':'old'}) is None
    qa_storage.finish(None,result_path=tmp_path/'old.json');assert path.exists()


def test_successful_qa_not_changed_by_maintenance_failure(managed,monkeypatch):
    cfg,ledger=managed;path,token=work(ledger);result=ledger.root/'qa.json';atomic_json(result,{'status':'pass'})
    def fail(*a,**k):raise OSError('injected maintenance disk failure')
    monkeypatch.setattr(token[0],'refresh',fail)
    qa_storage.finish(token,result_path=result)
    assert path.exists() and json.loads(result.read_text())['status']=='pass'
