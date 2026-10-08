"""Bounded trusted upload reconciliation, under the existing PG/host locks.

SQL commit and all references outrank missing host acknowledgments. No inode,
mtime, PID disappearance or journal gap alone authorizes deletion.
"""
import json
import os
import time
from pathlib import Path
from datetime import datetime,timezone,timedelta
from uuid import UUID
from .storage_lifecycle import Ledger,StorageError,atomic_json,bounded_path,sha,now,maintenance,reference_snapshot,strings,REFERENCE_TABLES,fsync_dir

def begin(cfg,partial,job_id,file_id):
    ledger=Ledger(cfg);expected=ledger.root/'uploads'/str(job_id)/(file_id+'.part')
    if Path(partial)!=expected:raise StorageError('STORAGE_PATH','Upload staging intent must use exact job/upload path')
    UUID(str(job_id));UUID(file_id)
    bounded_path(ledger.root,expected.relative_to(ledger.root))
    with ledger.lock():
        op={'version':'upload-intent-v2','operation_id':file_id,'instance_id':cfg['instance_id'],'test_session_id':cfg['test_session_id'],
            'job_id':str(job_id),'state':'staging','partial':str(expected.relative_to(ledger.root)),'created_at':now(),
            'lease_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'owner':file_id,'sha256':None,'size':None,'pin':None}
        ledger.operation(file_id,'upload',op)
    return op

def stage(cfg,receipt):
    ledger=Ledger(cfg)
    try:op=ledger.get_operation(receipt['id'])
    except StorageError as exc:
        if exc.code=='STORAGE_UNKNOWN':return  # Direct legacy trusted callers: never adopted by GC.
        raise
    if op['job_id']!=receipt['job_id']:raise StorageError('STORAGE_OWNER','Upload intent job changed')
    op.update(state='publishing',sha256=receipt['sha256'],size=receipt['size'],updated_at=now())
    ledger.operation(op['operation_id'],'upload',op)

def state(cfg,receipt,value):
    ledger=Ledger(cfg)
    try:op=ledger.get_operation(receipt['id'])
    except StorageError as exc:
        if exc.code=='STORAGE_UNKNOWN':return
        raise
    op.update(state=value,sha256=receipt['sha256'],size=receipt['size'],updated_at=now())
    ledger.operation(op['operation_id'],'upload',op)

def operation_valid(ledger,op):
    if op.get('version')!='upload-intent-v2' or op.get('instance_id')!=ledger.cfg['instance_id'] or op.get('test_session_id')!=ledger.cfg['test_session_id']:
        raise StorageError('STORAGE_OWNER','Upload intent identity differs')
    UUID(op['operation_id']);UUID(op['job_id'])
    if op['partial']!='uploads/'+op['job_id']+'/'+op['operation_id']+'.part' or op.get('owner')!=op['operation_id']:
        raise StorageError('STORAGE_OWNER','Upload intent path or owner differs')
    if op.get('sha256') and (len(op['sha256'])!=64 or any(c not in '0123456789abcdef' for c in op['sha256'])):
        raise StorageError('STORAGE_OWNER','Malformed upload content identity')
    bounded_path(ledger.root,op['partial'])
    for r in op.get('quarantine',[]):
        parts=Path(r['target']).parts
        if len(parts)!=3 or parts[:2]!=('gc-quarantine',op['operation_id']) or not parts[2].isdigit():raise StorageError('STORAGE_OWNER','Quarantine identity differs')
        bounded_path(ledger.root,r['target']);bounded_path(ledger.root,r['relative'])

def candidates(cfg,conn,ledger,clock):
    snapshot=reference_snapshot(conn,ledger.root);ops=ledger.operations('upload');found=[]
    rows={table:conn.execute('SELECT * FROM '+table).fetchall() for table in REFERENCE_TABLES}
    text={s for table in rows for row in rows[table] for s in strings(row)}
    committed={f['id']:f for row in rows['jobs'] for f in row['files']}
    grace=cfg['storage_policy'].get('upload_grace_seconds',86400)
    if grace<0:raise StorageError('STORAGE_POLICY','Upload grace cannot be negative')
    pending=[op for op in ops if op['state'] not in {'reclaimed','committed'}]
    for op in pending[:100]:
        why=[]
        try:operation_valid(ledger,op)
        except (StorageError,ValueError,KeyError) as exc:
            found.append({'id':op.get('operation_id'),'action':'retain','reasons':[getattr(exc,'code','STORAGE_OWNER')]});continue
        if op['operation_id'] in committed:
            receipt=committed[op['operation_id']]
            from .input_store import resolve
            resolve(cfg,receipt)  # Verify host receipt/blob, not merely ID text.
            found.append({'id':op['operation_id'],'action':'committed','reasons':['persisted jobs.files'], 'op':op});continue
        if op['state']=='committed':why.append('committed input retained even without current SQL reference')
        if snapshot['active']:why.append('active or recoverable jobs')
        if op.get('pin'):why.append('upload pin')
        try:
            created=datetime.fromisoformat(op['created_at']);lease=datetime.fromisoformat(op['lease_until'])
            if created.tzinfo is None or lease.tzinfo is None or clock<created or clock<lease:why.append('clock rollback or live/uncertain lease')
            if (clock-created).total_seconds()<grace:why.append('grace period not elapsed')
        except (ValueError,TypeError,KeyError):why.append('unknown creation/lease time')
        receipt=ledger.root/'receipts'/(op['operation_id']+'.json')
        paths=[bounded_path(ledger.root,op['partial']),bounded_path(ledger.root,'blobs/staging/'+op['operation_id']+'/content'),bounded_path(ledger.root,str(receipt.relative_to(ledger.root)))]
        if op['operation_id'] in text:why.append('file identity referenced by business/checkpoint data')
        for resource in ledger.resources():
            if resource['relative_path'] and resource['pin']:
                path=ledger.root/resource['relative_path']
                if path in paths or (op.get('sha256') and str(path).endswith('/'+op['sha256']+'/content')):why.append('resource pin')
        protected_paths=paths+[bounded_path(ledger.root,r['target']) for r in op.get('quarantine',[])]
        if any(Path(r['path'])==p or p.is_relative_to(Path(r['path'])) or Path(r['path']).is_relative_to(p) for r in snapshot['references'] for p in protected_paths):why.append('persisted path reference')
        blob=None
        if op.get('sha256'):
            blob=bounded_path(ledger.root,'blobs/sha256/'+op['sha256']+'/content')
            shared=any(o.get('sha256')==op['sha256'] and o['operation_id']!=op['operation_id'] and o['state']!='reclaimed' for o in ops)
            shared=shared or any(p==str(blob) for p in text)
            # Any host receipt not in this exact op is a conservative dependency.
            for resource in ledger.resources():
                if resource['kind']=='upload_receipt' and resource['state']!='reclaimed' and resource['relative_path']!=str(receipt.relative_to(ledger.root)):
                    if json.loads(resource['metadata']).get('blob_sha256')==op['sha256']:shared=True
            if not shared and not any(Path(r['path'])==blob or blob.is_relative_to(Path(r['path'])) or Path(r['path']).is_relative_to(blob) for r in snapshot['references']):paths.append(blob)
        for path in paths:
            if path.exists():
                if not path.is_file() or path.stat().st_nlink!=1:why.append('non-exclusive file')
                if path==blob and sha(path)!=op['sha256']:why.append('blob identity changed')
        found.append({'id':op['operation_id'],'action':'retain' if why else 'quarantine','reasons':sorted(set(why)),'paths':[str(p.relative_to(ledger.root)) for p in paths],'op':op})
    return found,len(pending)>100

def reconcile(cfg,*,apply=False,clock=None,limit_seconds=10):
    if not cfg.get('storage_policy',{}).get('enabled') or not cfg.get('storage_features',True):return {'managed':False,'results':[]}
    clock=clock or datetime.now(timezone.utc);started=time.monotonic();results=[]
    with maintenance(cfg) as (ledger,conn):
        found,truncated=candidates(cfg,conn,ledger,clock)
        for item in found:
            if time.monotonic()-started>limit_seconds:truncated=True;break
            report={k:v for k,v in item.items() if k!='op'}
            if not apply:results.append(report);continue
            op=item.get('op')
            if item['action']=='committed':
                if op['state']!='committed':
                    op.update(state='committed',reference_proof='persisted jobs.files',reconciled_at=now());ledger.operation(op['operation_id'],'upload',op)
                    ledger.journal('receipt_commit_reconciled',file_id=op['operation_id'],job_id=op['job_id'])
                results.append(report);continue
            if item['action']!='quarantine':results.append(report);continue
            q=bounded_path(ledger.root,'gc-quarantine/'+op['operation_id']);q.mkdir(parents=True,exist_ok=True,mode=0o700)
            # Save exact per-file proof before the first rename. On a subsequent
            # invocation recheck ALL SQL refs/leases/pins again, then resume.
            saved=op.get('quarantine',[])
            if not saved:
                for i,relative in enumerate(item['paths']):
                    path=bounded_path(ledger.root,relative)
                    if path.exists():saved.append({'relative':relative,'target':str((q/str(i)).relative_to(ledger.root)),'sha256':sha(path),'size':path.stat().st_size})
                op.update(state='quarantine',quarantine=saved);ledger.operation(op['operation_id'],'upload',op)
            for record in saved:
                original=bounded_path(ledger.root,record['relative']);target=bounded_path(ledger.root,record['target'])
                if original.exists() and target.exists():raise StorageError('STORAGE_CHANGED','Both quarantine and original exist')
                current=original if original.exists() else target
                if current.exists():
                    if current.stat().st_nlink!=1 or sha(current)!=record['sha256'] or current.stat().st_size!=record['size']:raise StorageError('STORAGE_CHANGED','Orphan changed since quarantine intent')
                    if current==original:os.rename(original,target);fsync_dir(original.parent);fsync_dir(q)
            # Durable tombstone must precede irreversible unlink.
            tomb={'operation_id':op['operation_id'],'instance':cfg['instance_id'],'files':saved,'reason':'Expired intent without persisted/host references','reference_summary':{'active':False,'uploaded_file_id_referenced':False},'at':now()}
            atomic_json(ledger.home/'tombstones'/(op['operation_id']+'.json'),tomb)
            for record in saved:
                target=bounded_path(ledger.root,record['target'])
                if target.exists():
                    if sha(target)!=record['sha256']:raise StorageError('STORAGE_CHANGED','Quarantined file identity changed')
                    target.unlink();fsync_dir(target.parent)
                for r in ledger.resources():
                    if r['relative_path']==record['relative']:ledger.state(r['id'],'reclaimed',reason='expired unreferenced upload, tombstone retained')
            op.update(state='reclaimed',reclaimed_at=now());ledger.operation(op['operation_id'],'upload',op)
            report['action']='reclaimed';results.append(report)
    return {'managed':True,'apply':apply,'results':results,'truncated':truncated,'seconds':time.monotonic()-started,'clock':clock.isoformat()}
