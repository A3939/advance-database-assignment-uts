import hashlib
import json
from pathlib import Path
from uuid import uuid4
import pytest

from arsia_pipeline import input_store
from arsia_pipeline.storage_lifecycle import Ledger, StorageError, atomic_json, provision


@pytest.fixture
def managed(tmp_path):
    cfg=provision(tmp_path/'session','instance-one',suite='input-tests')
    ledger=Ledger(cfg)
    p=ledger.home/'session.json';m=json.loads(p.read_text());m['state']='running';atomic_json(p,m)
    return cfg,ledger


def upload(cfg, payload=b'id,year\na,2024\n', name='test.csv', digest=None):
    fid=uuid4().hex;partial=Path(cfg['data_root'])/('upload-'+fid+'.part');partial.write_bytes(payload)
    receipt={'id':fid,'job_id':str(uuid4()),'name':name,'format':Path(name).suffix[1:],
        'size':len(payload),'sha256':digest or hashlib.sha256(payload).hexdigest()}
    try:return input_store.publish(cfg,partial,receipt)
    finally:partial.unlink(missing_ok=True)


def test_ten_uploads_single_blob_independent_identities(managed):
    cfg,ledger=managed
    receipts=[upload(cfg,name='changed.csv' if i%2 else 'test.csv') for i in range(10)]
    assert len({r['id'] for r in receipts})==10
    assert len({r['job_id'] for r in receipts})==10
    assert len({r['path'] for r in receipts})==1
    assert len([r for r in ledger.resources() if r['kind']=='raw_blob'])==1
    assert len([r for r in ledger.resources() if r['kind']=='upload_receipt'])==10
    assert len(list((ledger.root/'receipts').glob('*.json')))==10
    for r in receipts:assert input_store.resolve(cfg,r).read_bytes()==b'id,year\na,2024\n'


@pytest.mark.parametrize('fault',['hash','instance','name','format','size','path','symlink','content'])
def test_receipt_and_blob_tampering_refused(managed,tmp_path,fault):
    cfg,ledger=managed;r=upload(cfg)
    if fault=='hash':r['sha256']='0'*64
    elif fault=='instance':r['instance_id']='other'
    elif fault=='name':r['name']='other.csv'
    elif fault=='format':r['format']='xlsx'
    elif fault=='size':r['size']+=1
    elif fault=='path':r['path']=str(tmp_path/'external')
    elif fault=='symlink':
        p=Path(r['path']);p.rename(p.with_name('saved'));p.symlink_to(p.with_name('saved'))
    else:Path(r['path']).write_bytes(b'corrupt')
    with pytest.raises(StorageError):input_store.resolve(cfg,r)


def test_rollback_does_not_unlink_successful_blob(managed):
    cfg,ledger=managed;first=upload(cfg)
    # Publication precedes the SQL commit; an interrupted commit retains the
    # object, plus pending-commit receipt/journal for safe reconciliation.
    pending=upload(cfg)
    assert first['path']==pending['path']
    assert input_store.resolve(cfg,first).exists()
    assert not list(ledger.root.glob('*.part'))


def test_corrupt_existing_blob_not_overwritten(managed):
    cfg,ledger=managed;r=upload(cfg);Path(r['path']).write_bytes(b'damaged')
    with pytest.raises(StorageError,match='damaged'):upload(cfg)
    assert Path(r['path']).read_bytes()==b'damaged'


def test_server_does_not_trust_claimed_hash(managed):
    cfg,ledger=managed
    with pytest.raises(StorageError,match='actual'):upload(cfg,digest='0'*64)
    assert not [r for r in ledger.resources() if r['kind']=='raw_blob']


def test_legacy_receipt_works_without_migration(managed):
    cfg,ledger=managed;p=ledger.root/'legacy.csv';p.write_bytes(b'old')
    assert input_store.resolve(cfg,{'path':str(p),'sha256':hashlib.sha256(b'old').hexdigest(),'size':3})==p


@pytest.mark.parametrize('name',['test.csv','renamed.xlsx','bundle.zip','data.json','export.geojson','dictionary.pdf'])
def test_original_format_is_not_replaced_by_blob_name(managed,name):
    cfg,ledger=managed;r=upload(cfg,name=name)
    assert r['name']==name and r['format']==Path(name).suffix[1:]
    assert Path(r['path']).suffix==''


def test_disabled_old_config_has_no_storage_capability():
    assert not input_store.active({'mode':'local-test'})
    input_store.assert_accepting({'mode':'local-test'})
