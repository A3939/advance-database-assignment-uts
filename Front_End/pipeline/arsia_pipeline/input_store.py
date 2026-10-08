"""Instance-local immutable byte objects with independent upload receipts.

The existing PostgreSQL upload reservation serializes API publications. Host
locking also covers direct test callers. Rollback NEVER removes a shared blob.
Persisted jobs.files is the authoritative reference after the DB commits; the
host journal may conservatively retain an interrupted unpublished object.
"""
import json
import os
from pathlib import Path

from .storage_lifecycle import (Ledger, StorageError, atomic_json, bounded_path,
                               fsync_dir, now, sha, validate_managed)


def active(cfg):
    return cfg.get('storage_policy',{}).get('enabled') is True and cfg.get('storage_features',True) is True


def assert_accepting(cfg):
    if cfg.get('storage_policy',{}).get('enabled') is not True:return
    _,_,session=validate_managed(cfg)
    if session['state']!='running':
        raise StorageError('STORAGE_QUIESCING','This test session has stopped accepting work')


def publish(cfg, partial, receipt):
    ledger=Ledger(cfg)
    relative=str(Path(partial).relative_to(ledger.root))
    partial=bounded_path(ledger.root,relative,exists=True)
    actual=sha(partial)
    if actual!=receipt['sha256'] or partial.stat().st_size!=receipt['size']:
        raise StorageError('STORAGE_INPUT_CHANGED','Streamed upload differs from its actual staged bytes')
    object_dir=bounded_path(ledger.root,'blobs/sha256/'+actual)
    blob=bounded_path(ledger.root,'blobs/sha256/'+actual+'/content')
    with ledger.lock():
        assert_accepting(cfg)
        from .upload_gc import stage
        stage(cfg,receipt)
        ledger.journal('blob_publish_intent',file_id=receipt['id'],job_id=receipt['job_id'],sha256=actual)
        object_dir.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if object_dir.exists() or object_dir.is_symlink():
            if blob.is_symlink() or not blob.is_file() or sha(blob)!=actual or blob.stat().st_size!=receipt['size']:
                raise StorageError('STORAGE_BLOB_CORRUPT','Existing input object is damaged; reuse blocked')
        else:
            # Publish a complete nonempty directory. Directory rename cannot
            # replace another nonempty object, even outside our serial lock.
            staging=bounded_path(ledger.root,'blobs/staging/'+receipt['id'])
            ledger.journal('blob_staging_intent',relative_path=str(staging.relative_to(ledger.root)),
                           file_id=receipt['id'],sha256=actual)
            staging.mkdir(parents=True,mode=0o700)
            os.rename(partial,staging/'content');fsync_dir(staging)
            os.rename(staging,object_dir);fsync_dir(object_dir.parent)
        blob_id=ledger.register('raw_blob',str(blob.relative_to(ledger.root)))
        value={**receipt,'storage_version':'instance-cas-v1','instance_id':cfg['instance_id'],
               'uploaded_at':now(),'blob_resource_id':blob_id,'path':str(blob)}
        receipt_path=bounded_path(ledger.root,'receipts/'+receipt['id']+'.json')
        if receipt_path.exists():raise StorageError('STORAGE_RECEIPT','Upload receipt identity already exists')
        atomic_json(receipt_path,{k:v for k,v in value.items() if k!='path'})
        ledger.register('upload_receipt',str(receipt_path.relative_to(ledger.root)),job_id=receipt['job_id'],
                        metadata={'blob_sha256':actual,'file_id':receipt['id']})
        from .upload_gc import state
        state(cfg,receipt,'pending_commit')
        ledger.journal('receipt_pending_commit',file_id=receipt['id'],job_id=receipt['job_id'],sha256=actual)
        return value


def committed(cfg, receipt):
    from .upload_gc import state
    state(cfg,receipt,'committed')
    Ledger(cfg).journal('receipt_committed',file_id=receipt['id'],job_id=receipt['job_id'],sha256=receipt['sha256'])


def resolve(cfg, receipt):
    """Both legacy and CAS receipts remain readable within the explicit instance."""
    root=Path(cfg['data_root'])
    path=Path(receipt['path'])
    try:relative=path.relative_to(root)
    except ValueError:raise StorageError('STORAGE_PATH','Upload is outside its instance') from None
    path=bounded_path(root,relative,exists=True)
    if receipt.get('storage_version'):
        if receipt['storage_version']!='instance-cas-v1' or receipt.get('instance_id')!=cfg['instance_id']:
            raise StorageError('STORAGE_OWNER','Upload receipt belongs to another instance')
        if path!=root/'blobs/sha256'/receipt['sha256']/'content':
            raise StorageError('STORAGE_PATH','CAS receipt does not identify its declared object')
        disk=bounded_path(root,'receipts/'+receipt['id']+'.json',exists=True)
        original=json.loads(disk.read_text())
        if any(original.get(k)!=receipt.get(k) for k in ('id','job_id','name','format','size','sha256','instance_id')):
            raise StorageError('STORAGE_RECEIPT','Upload identity differs from its host receipt')
    if not path.is_file() or path.stat().st_size!=receipt['size'] or sha(path)!=receipt['sha256']:
        raise StorageError('STORAGE_BLOB_CORRUPT','Input content differs from its trusted upload receipt')
    return path
