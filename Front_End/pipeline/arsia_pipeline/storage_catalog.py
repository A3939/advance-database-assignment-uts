"""Explicit single-host test-space catalog. No historical discovery/adoption."""
import hashlib
import json
import sqlite3
import shutil
import time
from pathlib import Path
from uuid import uuid4
from contextlib import contextmanager
from .storage_lifecycle import Ledger,StorageError,atomic_json,bounded_path,now,sha,validate_managed

_TEST_CLAIM_HOOK=None  # Trusted subprocess synchronization; never user configurable.

class TestSpace:
    __test__=False
    def __init__(self,path):
        self.root=Path(path).absolute();marker=self.root/'space.json';self.path=self.root/'catalog.sqlite'
        if self.root.is_symlink() or marker.is_symlink() or self.path.is_symlink() or not marker.is_file() or not self.path.is_file():raise StorageError('STORAGE_CATALOG','Explicit catalog/marker unavailable')
        self.marker=json.loads(marker.read_text())
        if self.marker.get('version')!='storage-space-v1' or self.marker.get('root')!=str(self.root):raise StorageError('STORAGE_CATALOG','Space identity differs')
        if any(p.is_symlink() for p in self.root.parents):raise StorageError('STORAGE_CATALOG','Indirect space path')
        with self.db() as db:
            if dict(db.execute('SELECT key,value FROM meta'))!={'space_id':self.marker['space_id'],'marker_sha256':sha(marker)}:raise StorageError('STORAGE_CATALOG','Catalog marker mismatch')
    @classmethod
    def create(cls,path,*,budget_bytes=8*1024**3,reserve_bytes=2*1024**3,expanded_successes=2,unknown_volume_reserve=256*1024**2):
        if expanded_successes<1 or unknown_volume_reserve<=0:raise StorageError('STORAGE_POLICY','A positive N and unknown-volume reservation required')
        root=Path(path).absolute();root.mkdir(parents=True,exist_ok=False,mode=0o700)
        marker={'version':'storage-space-v1','space_id':uuid4().hex,'root':str(root),'created_at':now(),
                'policy':{'budget_bytes':budget_bytes,'reserve_bytes':reserve_bytes,'expanded_successes':expanded_successes,'unknown_volume_reserve':unknown_volume_reserve}}
        atomic_json(root/'space.json',marker)
        with sqlite3.connect(root/'catalog.sqlite') as db:
            db.executescript('''PRAGMA synchronous=FULL;
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE sessions(id TEXT PRIMARY KEY,instance TEXT UNIQUE,path TEXT UNIQUE,marker_sha TEXT NOT NULL,family TEXT NOT NULL,suite TEXT NOT NULL,
              state TEXT NOT NULL,compatibility TEXT NOT NULL,pin TEXT,reserved INTEGER NOT NULL,finished_at TEXT,claim TEXT,claim_until REAL);
            CREATE TABLE journal(id INTEGER PRIMARY KEY,event TEXT,at TEXT,payload TEXT);
            CREATE TABLE reservations(id TEXT PRIMARY KEY,bytes INTEGER NOT NULL,reason TEXT NOT NULL);
            ''');db.executemany('INSERT INTO meta VALUES(?,?)',[('space_id',marker['space_id']),('marker_sha256',sha(root/'space.json'))])
        (root/'catalog.sqlite').chmod(0o600)
        result=cls(root)
        from .storage_reservations import migrate
        migrate(result);return result
    def db(self):
        db=sqlite3.connect(self.path,timeout=0);db.row_factory=sqlite3.Row;db.execute('PRAGMA synchronous=FULL');return db
    def rows(self):
        with self.db() as db:return [dict(r) for r in db.execute('SELECT * FROM sessions ORDER BY finished_at,id')]
    def configuration(self,row):
        try:relative=Path(row['path']).relative_to(self.root)
        except ValueError:raise StorageError('STORAGE_CATALOG','Indexed session outside catalog boundary') from None
        home=bounded_path(self.root,relative,exists=True)
        cfg=json.loads((home/'lab/runtime.json').read_text());root,host,m=validate_managed(cfg)
        if host!=home or cfg['instance_id']!=row['instance'] or cfg['test_session_id']!=row['id'] or sha(root/'.storage-owner.json')!=row['marker_sha']:
            raise StorageError('STORAGE_CATALOG','Indexed session identity differs')
        if cfg.get('storage_space_id')!=self.marker['space_id'] or Path(cfg.get('storage_space',''))!=self.root or m.get('retention_family')!=row['family']:
            raise StorageError('STORAGE_CATALOG','Session is not enrolled in this catalog')
        return cfg,m
    def register(self,session,family):
        cfg=session.cfg;home=Path(cfg['storage_home'])
        if not home.is_relative_to(self.root) or home==self.root:raise StorageError('STORAGE_CATALOG','Session outside explicit space')
        from datetime import datetime
        manifest=session.ledger.session
        if manifest['state']!='creating' or datetime.fromisoformat(manifest['created_at'])<datetime.fromisoformat(self.marker['created_at']) or (manifest.get('docker') or {}).get('container_id'):
            raise StorageError('STORAGE_CATALOG','Only sessions created for this space may enroll')
        session.update(storage_space=str(self.root),storage_space_id=self.marker['space_id'])
        with self.db() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(cfg['test_session_id'],cfg['instance_id'],str(home),sha(home/'lab/.storage-owner.json'),family,session.ledger.session['suite'],'creating','{}',None,0,None,None,None))
            db.execute('INSERT INTO journal(event,at,payload) VALUES(?,?,?)',('registered',now(),json.dumps({'session':cfg['test_session_id'],'path':str(home)})))
    def update(self,session):
        m=json.loads((session.ledger.home/'session.json').read_text())
        identity={'baseline':m.get('baseline'),'input_set':m.get('input_set'),'database_schema':'arsia-imports-storage-current','instance_id':session.cfg['instance_id']}
        with self.db() as db:
            row=db.execute('SELECT * FROM sessions WHERE id=?',(session.cfg['test_session_id'],)).fetchone()
            if not row:raise StorageError('STORAGE_CATALOG','Session absent from explicit catalog')
            self.configuration(dict(row))
            db.execute('UPDATE sessions SET state=?,compatibility=?,finished_at=?,reserved=0 WHERE id=?',
                       (m['state'],json.dumps(identity,sort_keys=True),m.get('closed_at'),session.cfg['test_session_id']))
    def measure(self):
        own_files=[p for p in self.root.iterdir() if p.is_file() and not p.is_symlink()]
        if any(p.is_symlink() for p in self.root.iterdir()):raise StorageError('STORAGE_CATALOG','Indirect space resource')
        logical=sum(p.stat().st_size for p in own_files);allocated=sum(p.stat().st_blocks*512 for p in own_files);reservations=0;unknown=[];reasons=[]
        for row in self.rows():
            cfg,m=self.configuration(row)
            # Only explicitly registered bounded roots; never discover other artifacts.
            for path in Path(row['path']).rglob('*'):
                if path.is_symlink():
                    from .codex_resources import runtime_argv_link
                    if not runtime_argv_link(path, Path(cfg['data_root'])):
                        raise StorageError('STORAGE_CATALOG','Indirect registered file')
                    info=path.lstat();logical+=info.st_size;allocated+=info.st_blocks*512
                    continue
                if path.is_file():logical+=path.stat().st_size;allocated+=path.stat().st_blocks*512
            if m['state']!='archived':
                unknown.append({'identity':(m.get('docker') or {}).get('volume','session:'+row['id']),'session':row['id'],'category':'database_volume','reserved_bytes':self.marker['policy']['unknown_volume_reserve']})
            ledger=Ledger(cfg,read_only=True)
            with ledger.connect() as db:
                # Read-only old schema compatibility; space sessions have operations.
                operations=[json.loads(r['payload']) for r in db.execute("SELECT payload FROM operations WHERE kind='restore'")]
            for op in operations:
                if op['state']!='reclaimed':unknown.append({'identity':op.get('volume','restore:'+op['operation_id']),'operation':op['operation_id'],'category':'restore_volume','reserved_bytes':self.marker['policy']['unknown_volume_reserve']})
            if m['state'] not in {'archived','retained'} or m.get('policy',{}).get('keep_full'):reasons.append({'session':row['id'],'reason':m['state'] if not m.get('policy',{}).get('keep_full') else 'keep_full'})
        from .storage_reservations import held
        with self.db() as db:
            reservations=held(db)
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='reservation_resource_holds'").fetchone():
                known={r['identity'] for r in unknown}
                for r in db.execute('SELECT * FROM reservation_resource_holds'):
                    if r['identity'] not in known:unknown.append({'identity':r['identity'],'category':r['category'],'reserved_bytes':r['bytes'],'accounted_by':'durable_resource_hold'})
        return {'logical_bytes':logical,'allocated_bytes':allocated,'docker_reported_bytes':None,'unknown_components':unknown,
                'docker_reserved_bytes':sum(r['reserved_bytes'] for r in unknown),'operation_reserved_bytes':reservations,'protected':reasons,'measured_at':now(),
                'limits':'File logical/allocated are not summed. Docker reservation is conservative accounting, not a physical volume hard quota. Archives and necessary outputs continue to grow.'}
    def check_budget(self,additional):
        measured=self.measure();policy=self.marker['policy']
        if measured['logical_bytes']+measured['docker_reserved_bytes']+measured['operation_reserved_bytes']+additional>policy['budget_bytes']:
            raise StorageError('STORAGE_SPACE_BUDGET','Space budget including archives/unknown Docker reservations/backup peak exceeded; originals retained')
        if shutil.disk_usage(self.root).free<policy['reserve_bytes']+additional:raise StorageError('STORAGE_SPACE','Space reserve unavailable')
        return measured

    def reserve(self,identity,additional,reason,*,binding=None):
        if additional<0:raise StorageError('STORAGE_POLICY','Negative peak reservation')
        measured=self.check_budget(additional);policy=self.marker['policy']
        from .storage_reservations import held,supported
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Recheck concurrent reservations inside short transaction.
            held_bytes=held(db)
            # Another operation may have transferred peak to retained-resource accounting since measure().
            known={r['identity'] for r in measured['unknown_components']}
            transferred=sum(r['bytes'] for r in db.execute('SELECT * FROM reservation_resource_holds') if r['identity'] not in known) if supported(self) else 0
            held_bytes+=transferred
            if measured['logical_bytes']+measured['docker_reserved_bytes']+held_bytes+additional>policy['budget_bytes']:raise StorageError('STORAGE_SPACE_BUDGET','Concurrent reservation exceeds space budget')
            if binding:
                if not supported(self):raise StorageError('STORAGE_MIGRATION','Catalog migration required')
                op=db.execute('SELECT * FROM reservation_operations WHERE id=?',(binding['operation_id'],)).fetchone()
                if not op or op['space_id']!=self.marker['space_id']:raise StorageError('STORAGE_OWNER','Missing reservation intent')
                db.execute("INSERT INTO reservations(id,bytes,reason,space_id,operation_id,owner_token,state,created_at,updated_at,intent_sha256) VALUES(?,?,?,?,?,?,'reserved',?,?,?)",(identity,additional,reason,self.marker['space_id'],binding['operation_id'],binding['owner_token'],now(),now(),hashlib.sha256(op['intent'].encode()).hexdigest()))
            else:db.execute('INSERT INTO reservations(id,bytes,reason) VALUES(?,?,?)',(identity,additional,reason))
    def peak(self,additional,reason,*,operation):
        from .storage_reservations import peak
        return peak(self,operation,additional,reason)

    def pin(self,session_id,reason):
        row=next((r for r in self.rows() if r['id']==session_id),None)
        if not row:raise StorageError('STORAGE_CATALOG','Unregistered session')
        cfg,_=self.configuration(row)
        with Ledger(cfg).lock():
            from .test_session import TestSession
            TestSession(cfg).update(pin=reason)
            with self.db() as db:db.execute('UPDATE sessions SET pin=? WHERE id=?',(reason,session_id))

    def release(self,identity):
        raise StorageError('STORAGE_OWNER','Release requires operation execution proof and generation; use reservation reconciliation')
    def retain(self,session):
        self.update(session);rows=self.rows();validated=[]
        for row in rows:
            cfg,m=self.configuration(row);validated.append((row,cfg,m))
        group=[x for x in validated if x[0]['family']==session.ledger.session['retention_family'] and x[0]['suite']==session.ledger.session['suite'] and x[2].get('state')=='retained']
        group.sort(key=lambda x:(x[2].get('closed_at',''),x[0]['id']))
        n=self.marker['policy']['expanded_successes'];success=[x for x in group if x[2].get('success')];keep={x[0]['id'] for x in success[-n:]};failures={}
        for x in group:
            if not x[2].get('success'):failures.setdefault(x[2].get('failure_fingerprint') or x[0]['id'],[]).append(x)
        for groupf in failures.values():keep.update([groupf[0][0]['id'],groupf[-1][0]['id']])
        results=[]
        for row,cfg,m in group:
            if row['id'] in keep or m['policy'].get('keep_full') or row['pin']:continue
            claim=uuid4().hex
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE');changed=db.execute('UPDATE sessions SET claim=?,claim_until=? WHERE id=? AND (claim IS NULL OR claim_until<?)',(claim,time.time()+300,row['id'],time.time())).rowcount
            if not changed:results.append({'session':row['id'],'status':'deferred','reason':'another finalizer claim'});continue
            try:
                if _TEST_CLAIM_HOOK is not None:_TEST_CLAIM_HOOK(row['id'])
                from .test_session import TestSession
                target=TestSession(cfg)
                # Session lock, identity, pin and clean-shutdown checks run again in archive_database.
                if any(r['pin'] for r in target.ledger.resources()):raise StorageError('STORAGE_PIN','Pinned dependencies protect database')
                target.archive_database();self.update(target);results.append({'session':row['id'],'status':'archived'})
            except Exception as exc:
                results.append({'session':row['id'],'status':'blocked','code':getattr(exc,'code','STORAGE_CATALOG')})
            finally:
                with self.db() as db:
                    db.execute('UPDATE sessions SET claim=NULL,claim_until=NULL WHERE id=? AND claim=?',(row['id'],claim))
                    db.execute('INSERT INTO journal(event,at,payload) VALUES(?,?,?)',('retention_result',now(),json.dumps(results[-1])))
        return results
