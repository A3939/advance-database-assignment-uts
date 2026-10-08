"""Durable restore verification operations; never adopts legacy receipts."""
from contextlib import nullcontext
import json
import subprocess
import time
import re
from uuid import uuid4
from pathlib import Path
from .storage_lifecycle import StorageError, atomic_json, sha, now
from .storage_archive import verify

RESTORE_LABEL='arsia.storage.restore'

def docker(*args,**kw):
    from .test_session import docker as call
    return call(*args,**kw)

def explicit_absence(kind, identity, returncode, stderr):
    """Accept a complete, single-target daemon absence response, never a substring.

    Docker message words are case insensitive; the resource identity is not.
    Multiline diagnostics, connection errors and mismatched targets fail closed.
    """
    if kind not in {'container','volume'} or returncode != 1 or not isinstance(identity,str):return False
    if isinstance(stderr,bytes):
        try:stderr=stderr.decode('utf-8')
        except UnicodeError:return False
    if not isinstance(stderr,str) or len(stderr)>4096:return False
    message=stderr.strip()
    if '\n' in message or '\r' in message or not identity or any(c.isspace() for c in identity):return False
    patterns=([r'error(?: response from daemon)?:\s*no such volume:\s*(?P<target>\S+)',
               r'error response from daemon:\s*get\s+(?P<target>\S+):\s*no such volume'] if kind=='volume' else
              [r'error(?: response from daemon)?:\s*no such (?:object|container):\s*(?P<target>\S+)'])
    return any((m:=re.fullmatch(pattern,message,re.IGNORECASE)) and m['target']==identity for pattern in patterns)

def inspect_optional(kind, identity):
    if kind not in {'container','volume'}:raise StorageError('STORAGE_DOCKER_CHECK','Unsupported Docker inspection kind')
    args=('volume','inspect',identity) if kind=='volume' else ('inspect',identity)
    try:raw=docker(*args)
    except subprocess.CalledProcessError as exc:
        if explicit_absence(kind,identity,exc.returncode,exc.stderr):return None
        raise StorageError('STORAGE_DOCKER_CHECK','Docker inspection failed; absence not established') from exc
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise StorageError('STORAGE_DOCKER_CHECK','Docker inspection failed; absence not established') from exc
    try:
        values=json.loads(raw)
        if not isinstance(values,list) or len(values)!=1 or not isinstance(values[0],dict):raise ValueError()
        value=values[0]
        if kind=='volume':
            if value.get('Name')!=identity or 'Mounts' in value:raise ValueError()
        else:
            if not isinstance(value.get('Id'),str) or not isinstance(value.get('Name'),str) or not isinstance(value.get('Config'),dict) or not isinstance(value.get('State'),dict):raise ValueError()
            if identity not in {value['Id'],value['Name'].removeprefix('/')} :raise ValueError()
        return value
    except (ValueError,TypeError,KeyError) as exc:
        raise StorageError('STORAGE_DOCKER_CHECK','Malformed or mismatched Docker inspect response; absence not established') from exc

class RestoreOperation:
    def __init__(self,session):self.session=session;self.ledger=session.ledger
    def save(self,op,**fields):
        op.update(fields,updated_at=now())
        self.ledger.operation(op['operation_id'],'restore',op)
        atomic_json(self.ledger.home/('restore-'+op['operation_id']+'.json'),op)
    def source(self):
        archive=self.ledger.home/'archives/database.tar.gz'
        proof=json.loads((self.ledger.home/'database-archive.json').read_text())
        if archive.is_symlink() or sha(archive)!=proof['sha256']:
            raise StorageError('ARCHIVE_CHANGED','Restore source identity differs')
        verify(archive,expected=proof['manifest']);return archive,proof
    def labels(self,op):
        from .test_session import SESSION_LABEL,INSTANCE_LABEL
        return {SESSION_LABEL:self.session.cfg['test_session_id'],INSTANCE_LABEL:self.session.cfg['instance_id'],RESTORE_LABEL:op['operation_id']}
    def own(self,op):
        from .storage_lifecycle import validate_managed
        validate_managed(self.session.cfg)
        if op.get('version')!='restore-v2' or op.get('parent_instance')!=self.session.cfg['instance_id'] or op.get('parent_session')!=self.session.cfg['test_session_id']:
            raise StorageError('STORAGE_OWNER','No current complete restore intent; legacy receipts are read-only')
        labels=self.labels(op);c=inspect_optional('container',op['name']);v=inspect_optional('volume',op['volume'])
        if c:
            if c['Name'].lstrip('/')!=op['name'] or c['Image']!=op['image'] or (op.get('container_id') and c['Id']!=op['container_id']):
                raise StorageError('STORAGE_OWNER','Restore container identity changed')
            if any((c['Config'].get('Labels') or {}).get(k)!=value for k,value in labels.items()):
                raise StorageError('STORAGE_OWNER','Restore labels changed')
            m=c['Mounts']
            if len(m)!=1 or m[0]['Type']!='volume' or m[0]['Name']!=op['volume'] or m[0]['Destination']!='/var/lib/postgresql/data' or not m[0]['RW'] or c['HostConfig']['NetworkMode']!='none' or c['HostConfig'].get('PortBindings'):
                raise StorageError('STORAGE_SHARED','Unexpected restore mount or exposure')
        if v:
            if any((v.get('Labels') or {}).get(k)!=value for k,value in labels.items()) or (op.get('volume_created_at') and v.get('CreatedAt')!=op['volume_created_at']):
                raise StorageError('STORAGE_OWNER','Restore volume identity changed')
            users=docker('ps','-a','--filter','volume='+op['volume'],'--no-trunc','--format','{{.ID}}').decode().split()
            if users!=([c['Id']] if c else []):raise StorageError('STORAGE_SHARED','Restore volume has unknown users')
        elif c:raise StorageError('STORAGE_OWNER','Restore container volume is missing')
        return c,v
    def proof(self,op):
        archive,_=self.source()
        if sha(archive)!=op['archive_sha256']:
            raise StorageError('ARCHIVE_CHANGED','Source no longer matches operation')
        evidence=self.ledger.home/('restore-'+op['operation_id']+'-verification.json')
        log=self.ledger.home/('restore-'+op['operation_id']+'.log')
        if not evidence.is_file() or evidence.is_symlink() or sha(evidence)!=op.get('evidence_sha256') or not log.is_file() or log.is_symlink() or sha(log)!=op.get('log_sha256'):
            raise StorageError('RESTORE_EVIDENCE','Durable restore validation/log proof missing or changed')
        result=json.loads(evidence.read_text())
        if not result.get('passed') or result['archive_sha256']!=op['archive_sha256']:
            raise StorageError('RESTORE_EVIDENCE','Restore proof did not pass')
    def protected(self,op):
        if op.get('pin') or op.get('lease') or op.get('purpose')!='verify_only':
            raise StorageError('RESTORE_RETAINED','Restore is retained for use, pin or lease')
    def cleanup(self,op,hook=None):
        self.protected(op);self.proof(op)
        if op['state'] not in {'verified','verified_retained','cleanup_pending','reclaimed'}:
            raise StorageError('RESTORE_UNVERIFIED','Interrupted unverified copies are diagnostic evidence')
        c,v=self.own(op)
        if c:
            if c['State']['Running']:docker('stop','--time','30',c['Id'])
            c,v=self.own(op)
            if c['State']['Running'] or c['State']['ExitCode']!=0:
                raise StorageError('STORAGE_UNCLEAN','Restore copy did not stop normally')
        if c:
            stopped_log=self.ledger.home/('restore-'+op['operation_id']+'-stopped.log')
            stopped_log.write_bytes(docker('logs',c['Id']));stopped_log.chmod(0o600)
            with stopped_log.open('rb') as stream:
                import os;os.fsync(stream.fileno())
            atomic_json(self.ledger.home/('restore-'+op['operation_id']+'-stopped.json'),{'container_id':c['Id'],'state':c['State'],'mounts':c['Mounts']})
            self.save(op,stopped_log_sha256=sha(stopped_log))
        self.save(op,state='cleanup_pending')
        if c:docker('rm',c['Id'])
        if hook:hook('restore_container_removed')
        # Immediately recheck volume identity and all users after container removal.
        _,v=self.own(op);self.protected(self.ledger.get_operation(op['operation_id']))
        if v:docker('volume','rm',op['volume'])
        self.save(op,state='reclaimed',cleanup_result='pass',reclaimed_at=now())
        if self.session.cfg.get('storage_space'):
            from .storage_catalog import TestSpace
            space=TestSpace(self.session.cfg['storage_space'])
            with space.db() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='reservation_resource_holds'").fetchone():
                    db.execute('DELETE FROM reservation_resource_holds WHERE identity=? AND operation_id=? AND session_id=?',
                        (op['volume'],op['operation_id'],self.session.cfg['test_session_id']))
        self.ledger.journal('restore_reclaimed',operation_id=op['operation_id'])
        return op
    def reconcile(self,operation_id,hook=None,*,locked=False):
        with nullcontext() if locked else self.ledger.lock():
            op=self.ledger.get_operation(operation_id)
            if op['state'] in {'verified','verified_retained','cleanup_pending','reclaimed'}:
                try:return self.cleanup(op,hook)
                except Exception as exc:
                    self.save(op,cleanup_code=getattr(exc,'code','RESTORE_CLEANUP'))
                    raise
            c,v=self.own(op)
            if c and c['State']['Running']:docker('stop','--time','30',c['Id'])
            self.save(op,state='blocked',reason='Unverified interruption retained for diagnosis',container_id=c['Id'] if c else op.get('container_id'))
            return op
    def start(self,*,purpose='restore_for_use',keep=False,pin=None,hook=None):
        if purpose not in {'verify_only','restore_for_use'}:raise StorageError('RESTORE_PURPOSE','Explicit restore purpose required')
        from contextlib import nullcontext
        from .storage_catalog import TestSpace
        marker=uuid4().hex
        # Persist the exact restore intent before obtaining peak capacity or creating resources.
        with self.ledger.lock():
            archive,proof=self.source();receipt=proof['ownership']
            op={'version':'restore-v2','operation_id':marker,'parent_instance':self.session.cfg['instance_id'],'parent_session':self.session.cfg['test_session_id'],
                'name':'arsia-storage-restore-'+marker[:12],'volume':'arsia-storage-restore-'+marker[:12]+'-data','purpose':purpose,
                'archive_sha256':sha(archive),'image':receipt['image'],'executor_image':receipt['executor_image'],'state':'intent','created_at':now(),
                'pin':pin or ('explicit keep' if keep else ('restore for use' if purpose=='restore_for_use' else None)), 'lease':None,'container_id':None}
            self.save(op)
        peak=nullcontext()
        if self.session.cfg.get('storage_space'):
            from .storage_reservations import intent
            space=TestSpace(self.session.cfg['storage_space'])
            binding=intent(space,'restore',self.session.cfg['instance_id'],self.session.cfg['test_session_id'],self.ledger.home,
                {k:op[k] for k in ['name','volume','image','executor_image']},operation_id=marker)
            peak=space.peak(512*1024**2,'restore verification peak',operation=binding)
        with peak, self.ledger.lock():
            from .storage_lifecycle import assert_budget
            assert_budget(self.ledger,512*1024**2,space_reserved=bool(self.session.cfg.get('storage_space')))
            self.save(op);labels=[]
            for k,v in self.labels(op).items():labels.extend(['--label',k+'='+v])
            try:
                docker('volume','create',*labels,op['volume'])
                volume=inspect_optional('volume',op['volume']);self.save(op,state='restoring',volume_created_at=volume['CreatedAt'])
                if hook:hook('restore_volume_created')
                package=Path(__file__).resolve().parent.parent
                code='''from arsia_pipeline.storage_archive import restore,inventory
import os
from pathlib import Path
m=restore('/archive/database.tar.gz','/data/restored')
for r in m['members']:
 p=Path('/data/restored') if r['name']=='.' else Path('/data/restored')/r['name']
 os.chown(p,r['uid'],r['gid'])
assert inventory('/data/restored')==m['members']
for p in Path('/data/restored').iterdir():p.rename(Path('/data')/p.name)
Path('/data/restored').rmdir()
r=m['members'][0];os.chown('/data',r['uid'],r['gid']);os.chmod('/data',r['mode']);os.utime('/data',ns=(r['mtime_ns'],r['mtime_ns']))
assert inventory('/data')==m['members']
'''
                self.session.run_helper(receipt['executor_image'],[
                    {'type':'volume','source':op['volume'],'target':'/data','readonly':False},
                    {'type':'bind','source':str(archive.parent),'target':'/archive','readonly':True},
                    {'type':'bind','source':str(package),'target':'/code','readonly':True}],
                    'python',['-B','-c',code],caps=['CHOWN','FOWNER','DAC_OVERRIDE'],timeout=120,operation_id=op['operation_id'])
                identity=docker('run','-d','--name',op['name'],*labels,'--network=none','--pull=never','--memory=512m','--cpus=1','--pids-limit=128',
                    '--mount','type=volume,source='+op['volume']+',target=/var/lib/postgresql/data',op['image']).decode().strip()
                if hook:hook('restore_container_created')
                self.save(op,container_id=identity)
                self.own(op)
                for _ in range(100):
                    try:docker('exec',identity,'psql','-U','postgres','-d',self.session.cfg['database'],'-Atc','SELECT 1');break
                    except subprocess.CalledProcessError:time.sleep(.2)
                else:raise StorageError('RESTORE_START','Restored database did not become available')
                result=self.validate_queries(identity)
                log=self.ledger.home/('restore-'+marker+'.log');log.write_bytes(docker('logs',identity));log.chmod(0o600)
                with log.open('rb') as f:
                    import os;os.fsync(f.fileno())
                evidence=self.ledger.home/('restore-'+marker+'-verification.json')
                atomic_json(evidence,{'passed':True,'archive_sha256':op['archive_sha256'],'all_members_verified':True,**result,'restore_entry':'original verified archive retained'})
                self.save(op,state='verified',all_members_verified=True,tables=result['tables'],queries=result['queries'],evidence_sha256=sha(evidence),log_sha256=sha(log),validation_result='pass')
                if hook:hook('restore_verified')
                if purpose=='verify_only' and not op['pin']:
                    try:return self.cleanup(op,hook)
                    except Exception as exc:
                        self.save(op,cleanup_code=getattr(exc,'code','RESTORE_CLEANUP'));return op
                docker('stop','--time','30',identity);self.save(op,state='verified_retained',cleanup_result='retained');return op
            except BaseException as exc:
                self.save(op,state='blocked',reason=getattr(exc,'code',type(exc).__name__))
                c,_=self.own(op)
                if c:
                    path=self.ledger.home/('restore-'+marker+'-failed.log');path.write_bytes(docker('logs',c['Id']));path.chmod(0o600)
                    if c['State']['Running']:docker('stop','--time','30',c['Id'])
                raise
    def validate_queries(self,identity):
        import hashlib
        expected=json.loads((self.ledger.home/'database-before-stop.json').read_text());tables={}
        for table in expected['tables']:
            if not table.replace('_','').isalnum():raise StorageError('STORAGE_TABLE','Unexpected business table')
            values=docker('exec',identity,'psql','-U','postgres','-d',self.session.cfg['database'],'-Atc','SELECT row_to_json(t) FROM "'+table+'" t').decode().splitlines()
            content=sorted(json.dumps(json.loads(v),sort_keys=True,default=str,separators=(',',':')) for v in values)
            tables[table]={'count':len(values),'sha256':hashlib.sha256('\n'.join(content).encode()).hexdigest()}
        if tables!=expected['tables']:raise StorageError('RESTORE_QUERIES','Restored business rows differ')
        release=docker('exec',identity,'psql','-U','postgres','-d',self.session.cfg['database'],'-Atc','SELECT release_id FROM current_release').decode().strip() or None
        representative=json.loads(docker('exec',identity,'psql','-U','postgres','-d',self.session.cfg['database'],'-Atc',"SELECT json_build_object('crashes',count(*),'sources',count(distinct b.source_id)) FROM canonical_crash c JOIN batches b ON b.id=c.batch_id").decode())
        queries={'current_release':release,'canonical_summary':representative}
        if release!=expected['current_release'] or representative!=expected.get('queries',{}).get('canonical_summary',representative):raise StorageError('RESTORE_QUERIES','Restored release/query differs')
        return {'tables':tables,'queries':queries}
