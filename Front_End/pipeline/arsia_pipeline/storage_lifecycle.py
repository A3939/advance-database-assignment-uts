"""Opt-in, host-owned resource ledger. Never adopts an existing laboratory.

The journal remains outside the data root so a cold database archive cannot
remove the only recovery index. Mutation locks fail closed rather than wait.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

VERSION = 'arsia-storage-v1'
PURPOSE = 'storage-managed-test'
PROTECTED = {'uploading', 'queued', 'profiling', 'processing', 'validating',
             'publishing', 'recovering', 'cancel_requested', 'needs_input'}
KINDS = {'raw_blob', 'upload_receipt', 'execution_input', 'candidate_output',
         'qa_work_db', 'evidence', 'archive', 'container', 'database_volume'}
REFERENCE_TABLES = ('jobs', 'batches', 'releases', 'source_versions',
                    'adapter_versions', 'agent_sessions', 'agent_steps', 'attempts')


class StorageError(RuntimeError):
    kind = 'environment_dependency'
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.details = code, {}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.partial')
    try:
        with temporary.open('x', encoding='utf8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, indent=2, ensure_ascii=False, default=str, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        fsync_dir(path.parent)
    except OSError as exc:
        import errno
        raise StorageError('STORAGE_SPACE' if exc.errno==errno.ENOSPC else 'STORAGE_IO',
                           'Trusted storage could not persist its result; existing content retained') from exc
    finally:
        temporary.unlink(missing_ok=True)


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def bounded_path(root, relative, *, exists=False):
    root = Path(root)
    relative = Path(relative)
    if relative.is_absolute() or '..' in relative.parts or not relative.parts:
        raise StorageError('STORAGE_PATH', 'A restricted relative resource path is required')
    candidate = root / relative
    # Check every lexical component; resolve() alone conceals symlinks.
    for part in [root, *candidate.parents, candidate]:
        if part.is_symlink():
            raise StorageError('STORAGE_SYMLINK', 'Symlink resources are not managed')
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise StorageError('STORAGE_PATH', 'Resource escaped its registered root')
    if exists and not candidate.exists():
        raise StorageError('STORAGE_MISSING', 'Registered resource is missing; check archive state')
    return candidate


def enabled(cfg):
    return cfg.get('storage_policy', {}).get('enabled') is True


def validate_managed(cfg):
    if not enabled(cfg) or cfg.get('purpose') != PURPOSE:
        raise StorageError('STORAGE_UNMANAGED', 'Explicit managed test policy is required')
    root = Path(cfg['data_root'])
    boundary = Path(cfg['storage_home'])
    if root != boundary / 'lab' or not root.is_absolute() or not boundary.is_absolute():
        raise StorageError('STORAGE_OWNER', 'Managed root does not match its host session')
    for path in [boundary, root, root / '.storage-owner.json', boundary / 'session.json']:
        if path.is_symlink() or not path.exists():
            raise StorageError('STORAGE_OWNER', 'Managed session marker is missing or indirect')
    marker = json.loads((root / '.storage-owner.json').read_text())
    manifest = json.loads((boundary / 'session.json').read_text())
    expected = {k: cfg.get(k) for k in ('instance_id', 'test_session_id', 'purpose')}
    if any(not v for v in expected.values()) or marker != {**expected, 'version': VERSION}:
        raise StorageError('STORAGE_OWNER', 'Managed session ownership mismatch')
    if any(manifest.get(k) != v for k, v in expected.items()) or manifest.get('version') != VERSION:
        raise StorageError('STORAGE_OWNER', 'Host recovery receipt does not match this instance')
    if manifest.get('storage_space_id') and (cfg.get('storage_space_id')!=manifest['storage_space_id'] or cfg.get('storage_space')!=manifest.get('storage_space')):
        raise StorageError('STORAGE_CATALOG','Enrolled session cannot fall back to legacy discovery')
    if cfg['storage_policy'].get('version') != VERSION:
        raise StorageError('STORAGE_POLICY', 'Unknown storage policy version')
    return root, boundary, manifest


def provision(home, instance_id, *, suite, keep_full=False, budget_bytes=8*1024**3, session_id=None):
    """Only a new, empty session can acquire ownership; no implicit adoption."""
    home = Path(home).absolute()
    home.mkdir(parents=True, mode=0o700, exist_ok=False)
    root = home / 'lab'; root.mkdir(mode=0o700)
    identity = {'instance_id': instance_id, 'test_session_id': session_id or uuid4().hex, 'purpose': PURPOSE}
    policy = {'version': VERSION, 'enabled': True, 'keep_full': bool(keep_full),
              'expanded_successes': 2, 'budget_bytes': budget_bytes, 'reserve_bytes': 1024**3}
    atomic_json(root / '.storage-owner.json', {**identity, 'version': VERSION})
    atomic_json(home / 'session.json', {**identity, 'version': VERSION, 'suite': suite,
        'policy': policy, 'created_at': now(), 'state': 'creating', 'processes': [], 'docker': None})
    return {**identity, 'storage_home': str(home), 'data_root': str(root), 'storage_policy': policy}


class Ledger:
    def __init__(self, cfg, *, read_only=False):
        self.cfg = cfg
        self.read_only = read_only
        self.root, self.home, self.session = validate_managed(cfg)
        self.path = self.home / 'lifecycle.sqlite'
        if self.path.is_symlink(): raise StorageError('STORAGE_OWNER', 'Indirect resource ledger refused')
        if read_only:
            if not self.path.is_file():raise StorageError('STORAGE_UNKNOWN','Resource ledger is not yet available')
            return
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS resources(id TEXT PRIMARY KEY,kind TEXT NOT NULL,
                relative_path TEXT UNIQUE,job_id TEXT,attempt_id TEXT,run_id TEXT,
                state TEXT NOT NULL,bytes INTEGER,allocated_bytes INTEGER,sha256 TEXT,
                created_at TEXT NOT NULL,changed_at TEXT NOT NULL,pin TEXT,metadata TEXT NOT NULL,
                archive_id TEXT,reason TEXT);
            CREATE TABLE IF NOT EXISTS journal(id INTEGER PRIMARY KEY,event TEXT NOT NULL,
                resource_id TEXT,at TEXT NOT NULL,details TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,
                payload TEXT NOT NULL);
            ''')
            # Additive host-ledger migration: original tables/rows are unchanged.
            db.executescript('''CREATE TABLE IF NOT EXISTS migrations(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL);''')
            db.execute('INSERT OR IGNORE INTO migrations VALUES(?,?)',('storage-operations-v2',now()))
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect('file:'+str(self.path)+'?mode=ro',uri=True,timeout=0) if self.read_only else sqlite3.connect(self.path,timeout=0)
        db.row_factory = sqlite3.Row
        if not self.read_only:db.execute('PRAGMA synchronous=FULL')
        return db

    @contextmanager
    def lock(self):
        validate_managed(self.cfg)
        path = self.home / 'maintenance.lock'
        if path.is_symlink(): raise StorageError('STORAGE_OWNER', 'Indirect maintenance lock refused')
        with path.open('a') as stream:
            os.chmod(path, 0o600)
            try: fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise StorageError('STORAGE_BUSY', 'This session has an active storage operation') from None
            try: yield
            finally: fcntl.flock(stream, fcntl.LOCK_UN)

    def operation(self, identity, kind, payload):
        with self.connect() as db:
            row=db.execute('SELECT kind FROM operations WHERE id=?',(identity,)).fetchone()
            if row and row['kind']!=kind:raise StorageError('STORAGE_OWNER','Operation identity conflict')
            db.execute('INSERT INTO operations VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at',
                       (identity,kind,json.dumps(payload,sort_keys=True),now()))
        self.journal('operation_'+payload.get('state','recorded'),operation_id=identity,kind=kind)

    def get_operation(self, identity):
        with self.connect() as db:row=db.execute('SELECT payload FROM operations WHERE id=?',(identity,)).fetchone()
        if not row:raise StorageError('STORAGE_UNKNOWN','No registered current-version operation')
        return json.loads(row['payload'])

    def operations(self, kind):
        with self.connect() as db:return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM operations WHERE kind=? ORDER BY updated_at',(kind,))]

    def journal(self, event, resource_id=None, **details):
        with self.connect() as db:
            db.execute('INSERT INTO journal(event,resource_id,at,details) VALUES(?,?,?,?)',
                       (event, resource_id, now(), json.dumps(details, sort_keys=True)))

    def register(self, kind, relative, *, job_id=None, attempt_id=None, run_id=None, metadata=None):
        if kind not in KINDS: raise StorageError('STORAGE_KIND', 'Unknown resource class')
        path = bounded_path(self.root, relative, exists=True)
        # No recursion for status. Measured sizes enter at trusted registration.
        stat = path.stat()
        size = stat.st_size if path.is_file() else None
        allocated = stat.st_blocks * 512 if path.is_file() else None
        digest = sha(path) if path.is_file() else None
        relative = str(path.relative_to(self.root))
        parts=Path(relative).parts
        if len(parts)>3 and parts[0]=='attempts':
            from uuid import UUID
            try:
                UUID(parts[1]);UUID(parts[2])
                job_id=job_id or parts[1];attempt_id=attempt_id or parts[2]
            except ValueError:pass
        with self.connect() as db:
            old = db.execute('SELECT * FROM resources WHERE relative_path=?', (relative,)).fetchone()
            if old:
                if old['kind'] != kind or (old['sha256'] and old['sha256'] != digest):
                    raise StorageError('STORAGE_CHANGED', 'Registered content changed')
                return old['id']
            identity = uuid4().hex
            db.execute('INSERT INTO resources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (identity,kind,relative,str(job_id) if job_id else None,attempt_id,run_id,
                 'retained',size,allocated,digest,now(),now(),None,json.dumps(metadata or {}),None,None))
        self.journal('registered', identity, kind=kind, relative_path=relative)
        return identity

    def resources(self, limit=None):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM resources ORDER BY created_at'+(' LIMIT '+str(int(limit)) if limit else ''))]

    def get(self, identity):
        with self.connect() as db:
            row = db.execute('SELECT * FROM resources WHERE id=?', (identity,)).fetchone()
        if not row: raise StorageError('STORAGE_UNKNOWN', 'Resource is not registered in this session')
        return dict(row)

    def state(self, identity, state, *, reason=None, archive_id=None):
        with self.connect() as db:
            if db.execute('UPDATE resources SET state=?,reason=?,archive_id=coalesce(?,archive_id),changed_at=? WHERE id=?',
                (state,reason,archive_id,now(),identity)).rowcount != 1:
                raise StorageError('STORAGE_UNKNOWN', 'Unknown resource')
        self.journal(state, identity, reason=reason, archive_id=archive_id)

    def refresh(self, identity):
        resource=self.get(identity)
        path=bounded_path(self.root,resource['relative_path'],exists=True)
        paths=[path] if path.is_file() else list(path.rglob('*'))
        if any(p.is_symlink() for p in paths):raise StorageError('STORAGE_SYMLINK','Indirect measured resource')
        files=[p for p in paths if p.is_file()]
        with self.connect() as db:
            db.execute('UPDATE resources SET bytes=?,allocated_bytes=?,sha256=?,changed_at=? WHERE id=?',
                (sum(p.stat().st_size for p in files),sum(p.stat().st_blocks*512 for p in files),
                 sha(path) if path.is_file() else None,now(),identity))

    def external(self, kind, *, identity, metadata):
        if kind not in {'container','database_volume'}:
            raise StorageError('STORAGE_KIND','Only exclusive Docker resources have external identities')
        rid=kind+'-'+identity
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO resources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (rid,kind,None,None,None,None,'retained',None,None,None,now(),now(),None,
                 json.dumps(metadata),None,'exclusive test session ownership; Docker size unknown'))
        self.journal('docker_registered',rid,kind=kind)
        return rid

    def archive_record(self, archive_id, path):
        path=Path(path)
        if path.is_symlink() or path.parent!=self.home/'archives' or not path.is_file():
            raise StorageError('STORAGE_OWNER','Archive is outside its host recovery boundary')
        rid='archive-'+archive_id;info=path.stat()
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO resources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (rid,'archive',None,None,None,None,'retained',info.st_size,info.st_blocks*512,sha(path),
                 now(),now(),None,json.dumps({'archive_id':archive_id,'host_relative_path':str(path.relative_to(self.home))}),
                 archive_id,'verified recovery archive; no automatic expiry'))
        self.journal('archive_registered',rid,archive_id=archive_id)
        return rid

    def pin(self, identity, reason):
        with self.lock(), self.connect() as db:
            self.get(identity)
            db.execute('UPDATE resources SET pin=?,changed_at=? WHERE id=?', (reason,now(),identity))
        self.journal('pin' if reason else 'unpin', identity, reason=reason)

    def snapshot(self, job_id=None):
        rows = self.resources(limit=2001)
        truncated=len(rows)>2000;rows=rows[:2000]
        blob_receipts={}
        for r in rows:
            if r['kind']=='upload_receipt':
                digest=json.loads(r['metadata']).get('blob_sha256')
                blob_receipts[digest]=blob_receipts.get(digest,0)+1
        if job_id is not None:
            # Shared blobs use receipt references, rather than a misleading owner job.
            selected = [r for r in rows if r['job_id'] == str(job_id)]
            hashes = {json.loads(r['metadata']).get('blob_sha256') for r in selected}
            rows = selected + [r for r in rows if r['kind']=='raw_blob' and r['sha256'] in hashes]
        groups = {}
        for r in rows:
            g = groups.setdefault(r['kind'], {'logical_bytes':0, 'allocated_bytes':0, 'unknown_sizes':0, 'count':0})
            g['count'] += 1
            if r['state'] in {'reclaimed','archived'}:continue
            if r['bytes'] is None: g['unknown_sizes'] += 1
            else: g['logical_bytes'] += r['bytes']
            if r['allocated_bytes'] is not None: g['allocated_bytes'] += r['allocated_bytes']
        shared=sum(r['bytes'] or 0 for r in rows if r['kind']=='raw_blob' and blob_receipts.get(r['sha256'],0)>1)
        unique=sum(r['bytes'] or 0 for r in rows if r['kind']=='raw_blob' and blob_receipts.get(r['sha256'],0)<=1)
        return {'version':VERSION,'managed':True,'measured_at':now(),
            'measurement_scope':'registered resources in this test instance', 'estimated':True,
            'truncated':truncated,
            'shared_bytes':shared,'exclusive_raw_bytes':unique,
            'referenced_raw_bytes':shared+unique,'unregistered_bytes':None,
            'docker_bytes':None, 'groups':groups, 'budget_bytes':self.cfg['storage_policy']['budget_bytes'],
            'resources':[{'id':r['id'],'kind':r['kind'],'state':r['state'],
                          'logical_bytes':r['bytes'],'allocated_bytes':r['allocated_bytes'],
                          'retention_reason':'operator pin' if r['pin'] else ('retained for recovery or audit' if r['reason'] else None),
                          'restore_available':bool(r['archive_id'])} for r in rows]}


def strings(value):
    if isinstance(value, str): yield value
    elif isinstance(value, dict):
        for item in value.values(): yield from strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value: yield from strings(item)


def reference_snapshot(conn, root):
    """Read actual persisted JSON and evidence/checkpoint/registry paths.

    Work directories identify the attempt, not a dependency on every scratch
    byte. Active jobs protect all resources; completed paths in their result,
    sessions and steps still protect the exact referenced object/subdirectory.
    """
    active, references = [], []
    for table in REFERENCE_TABLES:
        for row in conn.execute('SELECT * FROM '+table).fetchall():
            if table == 'jobs' and row['status'] in PROTECTED:
                active.append({'job_id':str(row['id']),'status':row['status']})
            for key, value in row.items():
                if table == 'attempts' and key == 'work_dir': continue
                for text in strings(value):
                    if text.startswith('/'):
                        path = Path(text).resolve()
                        if path.is_relative_to(root):
                            references.append({'path':str(path),'reason':table+'.'+key})
                    elif key == 'evidence_path' and text:
                        # An ambiguous relative evidence location cannot authorize eviction.
                        references.append({'path':str(root),'reason':'relative agent evidence location'})
    return {'active':active,'references':references}


@contextmanager
def maintenance(cfg):
    """No external eviction while worker, upload or metadata mutation is live."""
    from . import store
    ledger = Ledger(cfg)
    with store.connect(cfg) as conn:
        if not conn.execute('SELECT pg_try_advisory_lock(%s) AS locked', (store.LOCK,)).fetchone()['locked']:
            raise StorageError('STORAGE_WORKER_BUSY','Worker owns this instance; maintenance deferred')
        try:
            with conn.transaction():
                if not conn.execute('SELECT pg_try_advisory_xact_lock(%s) AS locked',(store.LOCK+1,)).fetchone()['locked']:
                    raise StorageError('STORAGE_UPLOAD_BUSY','Upload reservation is active')
                for table in REFERENCE_TABLES:
                    conn.execute('LOCK TABLE '+table+' IN SHARE ROW EXCLUSIVE MODE NOWAIT')
                with ledger.lock():
                    yield ledger, conn
        finally: conn.execute('SELECT pg_advisory_unlock(%s)', (store.LOCK,))


def reasons(resource, snapshot, root):
    reasons = []
    if resource['pin']: reasons.append('pin: '+resource['pin'])
    if resource['kind']=='qa_work_db' and (resource['reason'] or '').startswith('unique failed QA'):
        reasons.append('unique failed QA work database retained')
    if snapshot['active']: reasons.append('active or recoverable jobs')
    if resource['relative_path'] is None:
        return reasons+[('verified recovery archive retained' if resource['kind']=='archive' else
                        'exclusive database resources require the stopped session finalizer')]
    path = root / resource['relative_path']
    for ref in snapshot['references']:
        referenced = Path(ref['path'])
        if referenced == path or referenced.is_relative_to(path) or path.is_relative_to(referenced):
            reasons.append('referenced by '+ref['reason'])
    if resource['kind'] in {'raw_blob','upload_receipt','candidate_output','evidence','archive'}:
        reasons.append('required input, published/evidence content or archive retention')
    if resource['state'] not in {'retained','blocked','archive_planned','archiving','verified','eviction_pending'}:
        reasons.append('not an expanded resource')
    return sorted(set(reasons))


def plan(cfg):
    with maintenance(cfg) as (ledger, conn):
        snapshot = reference_snapshot(conn, ledger.root)
        resources = ledger.resources()
        entries = [{'id':r['id'],'kind':r['kind'],'reasons':reasons(r,snapshot,ledger.root),
                    'eligible':not reasons(r,snapshot,ledger.root), 'state':r['state'],
                    'changed_at':r['changed_at'],'sha256':r['sha256']} for r in resources]
        payload = {'version':VERSION,'instance_id':cfg['instance_id'],'test_session_id':cfg['test_session_id'],
                   'entries':entries,'created_at':now(),'id':uuid4().hex}
        with ledger.connect() as db:
            db.execute('INSERT INTO plans VALUES(?,?,?)',(payload['id'],payload['created_at'],json.dumps(payload)))
        ledger.journal('plan', plan_id=payload['id'])
        return payload


def assert_budget(ledger, additional_bytes=0, *, space_reserved=False):
    # A bounded scan of THIS new session only; never executed by page polling.
    logical = 0
    for parent, dirs, files in os.walk(ledger.home, followlinks=False):
        for name in dirs + files:
            path = Path(parent)/name
            if path.is_symlink():
                from .codex_resources import runtime_argv_link
                if not runtime_argv_link(path, ledger.root):
                    raise StorageError('STORAGE_SYMLINK','Indirect session resource refused')
        # Count the link inode, never the executable outside this session.
        logical += sum((Path(parent)/name).lstat().st_size for name in files)
    if ledger.cfg.get('storage_space') and not space_reserved:
        from .storage_catalog import TestSpace
        TestSpace(ledger.cfg['storage_space']).check_budget(additional_bytes)
    policy = ledger.cfg['storage_policy']
    if logical + additional_bytes > policy['budget_bytes']:
        raise StorageError('STORAGE_BUDGET','Test session storage budget exceeded; originals retained')
    if shutil.disk_usage(ledger.home).free < policy['reserve_bytes'] + additional_bytes:
        raise StorageError('STORAGE_SPACE','Insufficient reserve for a verified backup; originals retained')
