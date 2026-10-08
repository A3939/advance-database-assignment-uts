"""Durable peak ownership for explicit test spaces, with fail-closed reconciliation.

No discovery, PID guessing, TTL reclamation, or automatic legacy migration.
Lock order: operation flock -> session flock -> short catalog transaction.
"""
from contextlib import contextmanager
import fcntl
import json
import hashlib
import os
from pathlib import Path
import time
from uuid import uuid4
from .storage_lifecycle import StorageError, bounded_path, now

VERSION='storage-reservations-v2'
_TEST_OPERATION_HOOK=None


def migrate(space):
    """Explicit append migration. Old records remain charged and unresolvable."""
    with space.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS catalog_migrations(version TEXT PRIMARY KEY,applied_at TEXT NOT NULL)')
        columns={r['name'] for r in db.execute('PRAGMA table_info(reservations)')}
        additions={'space_id':'TEXT','operation_id':'TEXT','owner_token':'TEXT','generation':'INTEGER NOT NULL DEFAULT 0',
            'state':"TEXT NOT NULL DEFAULT 'legacy_unresolved'",'created_at':'TEXT','updated_at':'TEXT',
            'released_at':'TEXT','release_reason':'TEXT','evidence':'TEXT','intent_sha256':'TEXT'}
        for column,definition in additions.items():
            if column not in columns:db.execute('ALTER TABLE reservations ADD COLUMN '+column+' '+definition)
        db.execute('''CREATE TABLE IF NOT EXISTS reservation_operations(
            id TEXT PRIMARY KEY, space_id TEXT NOT NULL, kind TEXT NOT NULL,
            instance_id TEXT NOT NULL, session_id TEXT NOT NULL, home TEXT NOT NULL,
            intent TEXT NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS reservation_resource_holds(
            identity TEXT PRIMARY KEY, bytes INTEGER NOT NULL, operation_id TEXT NOT NULL,
            session_id TEXT NOT NULL, category TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        db.execute('INSERT OR IGNORE INTO catalog_migrations VALUES(?,?)',(VERSION,now()))


def supported(space):
    with space.db() as db:return 'state' in {r['name'] for r in db.execute('PRAGMA table_info(reservations)')}


def held(db):
    columns={r['name'] for r in db.execute('PRAGMA table_info(reservations)')}
    query='SELECT coalesce(sum(bytes),0) FROM reservations'+(" WHERE state!='released'" if 'state' in columns else '')
    return db.execute(query).fetchone()[0]


def status(space):
    with space.db() as db:
        records=[dict(r) for r in db.execute('SELECT * FROM reservations ORDER BY id')]
        operations=[dict(r) for r in db.execute('SELECT * FROM reservation_operations ORDER BY id')] if supported(space) else []
    return {'version':VERSION,'space_id':space.marker['space_id'],'records':records,'operations':operations,
        'active_bytes':sum(r['bytes'] for r in records if r.get('state')!='released'),
        'legacy_unresolved':[r['id'] for r in records if not r.get('operation_id')], 'read_only':True}


@contextmanager
def execution_lock(space,operation_id):
    if len(operation_id)!=32 or any(c not in '0123456789abcdef' for c in operation_id):raise StorageError('STORAGE_OWNER','Invalid operation identity')
    folder=bounded_path(space.root,'operation-locks');folder.mkdir(exist_ok=True,mode=0o700)
    path=bounded_path(space.root,'operation-locks/'+operation_id+'.lock')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise StorageError('STORAGE_BUSY','Operation execution lock is still held') from None
        yield
    finally:os.close(fd)


def intent(space,kind,instance_id,session_id,home,expected,operation_id=None):
    if not supported(space):raise StorageError('STORAGE_MIGRATION','Explicit catalog migration required; legacy reservations remain held')
    if kind not in {'create','backup','restore'}:raise StorageError('STORAGE_OWNER','Unsupported reservation operation')
    home=Path(home).absolute()
    if home==space.root:raise StorageError('STORAGE_OWNER','Session cannot own the catalog root')
    try:relative=home.relative_to(space.root)
    except ValueError:raise StorageError('STORAGE_OWNER','Operation home outside explicit space') from None
    bounded_path(space.root,relative)
    identity=operation_id or uuid4().hex;at=now()
    payload={'version':VERSION,'operation_id':identity,'kind':kind,'space_id':space.marker['space_id'],
        'instance_id':instance_id,'session_id':session_id,'home':str(home),'expected':expected,
        'record_location':str(home/('restore-'+identity+'.json')) if kind=='restore' else str(space.path)+'#reservation_operations/'+identity}
    with space.db() as db:
        db.execute('INSERT INTO reservation_operations VALUES(?,?,?,?,?,?,?,?,?,?)',
            (identity,space.marker['space_id'],kind,instance_id,session_id,str(home),json.dumps(payload,sort_keys=True),'intent',at,at))
    return payload


def checked_intent(space,row):
    with space.db() as db:op=db.execute('SELECT * FROM reservation_operations WHERE id=?',(row['operation_id'],)).fetchone()
    if not op:raise StorageError('STORAGE_OWNER','Reservation has no durable operation')
    op=dict(op);payload=json.loads(op['intent'])
    if hashlib.sha256(op['intent'].encode()).hexdigest()!=row.get('intent_sha256'):
        raise StorageError('STORAGE_OWNER','Bound reservation intent changed')
    for key in ['space_id','instance_id','session_id','home','kind']:
        if payload[key]!=op[key]:raise StorageError('STORAGE_OWNER','Operation receipt identity changed')
    if row['space_id']!=space.marker['space_id'] or op['space_id']!=space.marker['space_id'] or payload['operation_id']!=row['operation_id']:
        raise StorageError('STORAGE_OWNER','Reservation belongs to another space/operation')
    bounded_path(space.root,Path(payload['home']).relative_to(space.root))
    return payload


def bound_session(space,op):
    from .test_session import TestSession
    rows=[r for r in space.rows() if r['id']==op['session_id']]
    if len(rows)!=1:raise StorageError('STORAGE_OWNER','Resource home exists without complete explicit enrollment')
    row=rows[0];cfg,_=space.configuration(row)
    if row['instance']!=op['instance_id'] or row['path']!=op['home']:raise StorageError('STORAGE_OWNER','Operation/session identity differs')
    return TestSession(cfg)


def settle(space,op,*,completed=False):
    """Reconcile existing work only; no import, allocation or restoration starts."""
    from .storage_restore import RestoreOperation,inspect_optional
    from .test_session import docker,SESSION_LABEL,INSTANCE_LABEL
    home=Path(op['home']);expected=op['expected'];held_resources=[]
    if not home.exists():
        if op['kind']!='create':raise StorageError('STORAGE_OWNER','Registered operation home disappeared')
        if inspect_optional('container',expected['name']) or inspect_optional('volume',expected['volume']):
            raise StorageError('STORAGE_OWNER','Unregistered creation resources exist; peak retained')
        return {'result':'never_started','held_resources':[],'exact_absence':True,
                'observed_resources':[{'identity':expected['volume'],'present':False}]}
    session=bound_session(space,op)
    with session.ledger.lock():
        session.recover_helpers()
        if op['kind']=='restore':
            manager=RestoreOperation(session);restore=session.ledger.get_operation(op['operation_id'])
            if any(restore.get(k)!=expected.get(k) for k in ['name','volume','image']):raise StorageError('STORAGE_OWNER','Restore expectation changed')
            if not completed:
                try:manager.reconcile(op['operation_id'],locked=True)
                except StorageError as exc:
                    if exc.code!='RESTORE_RETAINED':raise
            restore=session.ledger.get_operation(op['operation_id']);c,v=manager.own(restore)
            if c and c['State']['Running']:
                docker('stop','--time','30',c['Id']);c,v=manager.own(restore)
                if c and c['State']['Running']:raise StorageError('STORAGE_BUSY','Restore copy remains running')
            if v:held_resources.append({'identity':expected['volume'],'category':'restore_volume','accounted_by':'session_restore_operation','bytes':space.marker['policy']['unknown_volume_reserve']})
            if restore['state']=='reclaimed' and (c or v):raise StorageError('STORAGE_OWNER','Reclaimed restore still has resources')
        else:
            manifest=json.loads((home/'session.json').read_text());receipt=manifest.get('docker')
            if not receipt or any(receipt.get(k)!=expected.get(k) for k in ['name','volume','image']):raise StorageError('STORAGE_OWNER','Database receipt differs from reservation intent')
            if op['kind']=='backup' and manifest['state']=='db_eviction_pending':session.reconcile_database_eviction(locked=True)
            c=inspect_optional('container',expected['name']);v=inspect_optional('volume',expected['volume'])
            if c:
                session.own()
                # A normally completed create hands a running server to its session.
                if c['State']['Running'] and not (completed and op['kind']=='create'):
                    docker('stop','--time','30',c['Id']);c=inspect_optional('container',expected['name'])
                    if not c or c['State']['Running']:raise StorageError('STORAGE_BUSY','Owned server did not settle')
                if not c['State']['Running'] and c['State']['ExitCode']!=0:raise StorageError('STORAGE_UNCLEAN','Unclean database exit; peak retained')
            if v:
                labels=v.get('Labels') or {}
                if labels.get(SESSION_LABEL)!=op['session_id'] or labels.get(INSTANCE_LABEL)!=op['instance_id']:raise StorageError('STORAGE_OWNER','Volume ownership differs')
                users=docker('ps','-a','--filter','volume='+expected['volume'],'--no-trunc','--format','{{.ID}}').decode().split()
                if users!=([c['Id']] if c else []):raise StorageError('STORAGE_SHARED','Database volume has unregistered users')
                held_resources.append({'identity':expected['volume'],'category':'database_volume','accounted_by':'registered_session','bytes':space.marker['policy']['unknown_volume_reserve']})
            elif c:raise StorageError('STORAGE_OWNER','Container has lost its database volume')
            manifest=json.loads((home/'session.json').read_text())
            if manifest['state']=='archived' and (c or v):raise StorageError('STORAGE_OWNER','Archived session has unaccounted resources')
            if op['kind']=='backup' and manifest['state']=='archived':
                from .storage_archive import verify
                from .storage_lifecycle import sha
                archive=home/'archives/database.tar.gz';proof=json.loads((home/'database-archive.json').read_text())
                if sha(archive)!=proof['sha256']:raise StorageError('ARCHIVE_CHANGED','Backup changed before reservation release')
                verify(archive,expected=proof['manifest'])
            if not completed and op['kind']=='create' and manifest['state'] in {'creating','creation_interrupted'}:
                session.update(state='creation_interrupted',maintenance_code='CREATION_PRESERVED')
        space.update(session)
        measured=space.measure()
        for resource in held_resources:
            if not any(x['category']==resource['category'] and (x.get('operation')==op['operation_id'] if resource['category']=='restore_volume' else x.get('session')==op['session_id']) for x in measured['unknown_components']):
                raise StorageError('STORAGE_ACCOUNTING','Retained resource is not charged')
        return {'result':'completed' if completed else 'settled','held_resources':held_resources,
                'session_id':op['session_id'],'observed_resources':[{'identity':expected['volume'],'present':bool(v)}],
                'docker_reserved_bytes':measured['docker_reserved_bytes']}


def release(space,row,owner,generation,evidence):
    with space.db() as db:
        db.execute('BEGIN IMMEDIATE')
        changed=db.execute("UPDATE reservations SET state='released',released_at=?,updated_at=?,release_reason=?,evidence=? WHERE id=? AND owner_token=? AND generation=? AND state IN ('reserved','active','blocked')",
            (now(),now(),evidence['result'],json.dumps(evidence,sort_keys=True),row['id'],owner,generation)).rowcount
        if changed!=1:raise StorageError('STORAGE_OWNER','Reservation execution generation changed; no release')
        # Transfer peak accounting to durable resource holds atomically with release.
        # This also closes a concurrent reserve's stale filesystem measurement window.
        for item in evidence.get('observed_resources',[]):
            if not item['present']:db.execute('DELETE FROM reservation_resource_holds WHERE identity=?',(item['identity'],))
        for resource in evidence.get('held_resources',[]):
            db.execute('INSERT INTO reservation_resource_holds VALUES(?,?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET bytes=excluded.bytes,operation_id=excluded.operation_id,updated_at=excluded.updated_at',
                (resource['identity'],resource['bytes'],row['operation_id'],evidence['session_id'],resource['category'],now()))
        db.execute("UPDATE reservation_operations SET state='settled',updated_at=? WHERE id=?",(now(),row['operation_id']))
        db.execute('INSERT INTO journal(event,at,payload) VALUES(?,?,?)',('reservation_released',now(),json.dumps({'reservation_id':row['id'],'operation_id':row['operation_id'],'generation':generation,'evidence':evidence})))


def blocked(space,identity,owner,generation,exc):
    with space.db() as db:db.execute("UPDATE reservations SET state='blocked',updated_at=?,evidence=? WHERE id=? AND owner_token=? AND generation=? AND state!='released'",
        (now(),json.dumps({'result':'blocked','code':getattr(exc,'code',type(exc).__name__),'message':str(exc)}),identity,owner,generation))


@contextmanager
def peak(space,payload,amount,reason):
    identity=uuid4().hex;owner=uuid4().hex
    with execution_lock(space,payload['operation_id']):
        space.reserve(identity,amount,reason,binding={'operation_id':payload['operation_id'],'owner_token':owner})
        with space.db() as db:
            db.execute("UPDATE reservations SET state='active',updated_at=? WHERE id=?",(now(),identity))
            db.execute("UPDATE reservation_operations SET state='active',updated_at=? WHERE id=?",(now(),payload['operation_id']))
        try:
            if _TEST_OPERATION_HOOK:_TEST_OPERATION_HOOK('reserved',payload)
            yield identity
        except BaseException as exc:
            blocked(space,identity,owner,0,exc);raise
        else:
            try:
                evidence=settle(space,payload,completed=True)
                release(space,{'id':identity,'operation_id':payload['operation_id']},owner,0,evidence)
            except Exception as exc:
                blocked(space,identity,owner,0,exc)
                raise


def reconcile(space,*,limit=100,seconds=10,apply=False):
    if not 1<=limit<=100 or not 0<seconds<=10:raise StorageError('STORAGE_POLICY','Bounded reservation reconciliation required')
    started=time.monotonic();rows=status(space)['records'];results=[]
    for row in rows:
        if time.monotonic()-started>=seconds or len(results)>=limit:break
        if row.get('state')=='released':continue
        if not row.get('operation_id'):
            results.append({'id':row['id'],'status':'blocked','code':'LEGACY_UNRESOLVED'});continue
        if not apply:
            results.append({'id':row['id'],'status':'requires_execution_lock_and_resource_checks'});continue
        owner=uuid4().hex;generation=None
        try:
            with execution_lock(space,row['operation_id']):
                with space.db() as db:
                    db.execute('BEGIN IMMEDIATE');fresh=db.execute('SELECT * FROM reservations WHERE id=?',(row['id'],)).fetchone()
                    if fresh['state']=='released':continue
                    generation=fresh['generation']+1
                    db.execute('UPDATE reservations SET owner_token=?,generation=?,updated_at=? WHERE id=?',(owner,generation,now(),row['id']))
                    row=dict(fresh)
                op=checked_intent(space,row)
                # Each Docker call obeys the remaining whole reconciliation deadline.
                from .test_session import DOCKER_DEADLINE
                token=DOCKER_DEADLINE.set(started+seconds)
                try:evidence=settle(space,op)
                finally:DOCKER_DEADLINE.reset(token)
                release(space,row,owner,generation,evidence)
                results.append({'id':row['id'],'status':'released','evidence':evidence})
        except Exception as exc:
            if generation is not None:blocked(space,row['id'],owner,generation,exc)
            results.append({'id':row['id'],'status':'deferred' if getattr(exc,'code',None)=='STORAGE_BUSY' else 'blocked','code':getattr(exc,'code',type(exc).__name__),'message':str(exc)})
    final=status(space)
    return {'results':results,'active_bytes':final['active_bytes'],'pending':sum(r.get('state')!='released' for r in final['records']),
        'seconds':time.monotonic()-started,'apply':apply,'limit':limit}
