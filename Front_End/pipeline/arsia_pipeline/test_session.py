"""Shared lifecycle for NEW, exclusive acceptance sessions.

Docker creation intent is durable before creation. Existing labs are never
adopted. Finalization is invoked by the test lifecycle, not a timer or agent.
"""
from contextvars import ContextVar
from contextlib import nullcontext
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from uuid import uuid4

from .storage_lifecycle import (Ledger, StorageError, VERSION, atomic_json,
    assert_budget, maintenance, now, provision, reference_snapshot, sha)
from .storage_archive import create, verify, restore

SESSION_LABEL = 'arsia.storage.session'
INSTANCE_LABEL = 'arsia.storage.instance'
DOCKER_DEADLINE=ContextVar('storage_docker_deadline',default=None)


def docker(*args, timeout=60):
    deadline=DOCKER_DEADLINE.get()
    if deadline is not None:
        remaining=deadline-time.monotonic()
        if remaining<=0:raise StorageError('STORAGE_DEADLINE','Bounded Docker reconciliation deadline reached')
        timeout=min(timeout,remaining)
    return subprocess.check_output(['docker',*map(str,args)],timeout=timeout,stderr=subprocess.PIPE)


class TestSession:
    __test__ = False
    def __init__(self, cfg):
        self.cfg = cfg
        self.ledger = Ledger(cfg)

    @classmethod
    def create(cls, home, *, suite, postgres_image, executor_image, keep_full=False,
               storage_features=True, budget_bytes=8*1024**3, space=None, retention_family="default", expanded_successes=2):
        instance=uuid4().hex;session_id=uuid4().hex
        image=docker('image','inspect',postgres_image,'--format','{{.Id}}').decode().strip()
        executor=docker('image','inspect',executor_image,'--format','{{.Id}}').decode().strip()
        name='arsia-storage-'+instance[:12];volume=name+'-data'
        space_obj=None;operation=nullcontext()
        if space:
            from .storage_catalog import TestSpace
            from .storage_reservations import intent
            space_obj=TestSpace(space)
            rows=space_obj.rows()
            if rows:
                cfg,manifest=space_obj.configuration(rows[-1]);space_obj.retain(cls(cfg))
            op=intent(space_obj,'create',instance,session_id,home,{'name':name,'volume':volume,'image':image,'executor_image':executor})
            operation=space_obj.peak(512*1024**2,'new exclusive database + creation peak',operation=op)
        with operation:
            return cls._create(home,suite=suite,image=image,executor=executor,keep_full=keep_full,
                storage_features=storage_features,budget_bytes=budget_bytes,space_obj=space_obj,
                retention_family=retention_family,expanded_successes=expanded_successes,instance=instance,session_id=session_id,operation=op if space_obj else None)

    @classmethod
    def _create(cls,home,*,suite,image,executor,keep_full,storage_features,budget_bytes,space_obj,
                retention_family,expanded_successes,instance,session_id,operation):
        managed = provision(home,instance,suite=suite,keep_full=keep_full,budget_bytes=budget_bytes,session_id=session_id)
        root, home = Path(managed['data_root']), Path(managed['storage_home'])
        password=secrets.token_urlsafe(32)
        env=home/'postgres.env'
        env.write_text('POSTGRES_PASSWORD='+password+'\nPOSTGRES_DB=arsia_imports_storage\n');env.chmod(0o600)
        name='arsia-storage-'+instance[:12];volume=name+'-data'
        cfg={**managed,'mode':'local-test','database':'arsia_imports_storage',
            'dsn':'','container':name,'volume':volume,'executor_image':executor,
            'agent_engine':'codex','agent_profile':'expanded-v1',
            'knowledge_root':str(root/'recipes'), 'storage_features':bool(storage_features),
            'executor_limits':{'memory_mb':2048,'cpus':2,'seconds':120}}
        if space_obj:
            cfg.update(storage_space=str(space_obj.root),storage_space_id=space_obj.marker['space_id'])
            cfg['storage_policy']['expanded_successes']=space_obj.marker['policy']['expanded_successes']
        else:cfg['storage_policy']['expanded_successes']=expanded_successes
        session=cls(cfg)
        session.update(retention_family=retention_family,policy=cfg['storage_policy'])
        owned={'name':name,'volume':volume,'image':image,'executor_image':executor,
               'session_id':cfg['test_session_id'],'instance_id':instance,'container_id':None}
        session.update(state='creating',docker=owned)
        atomic_json(root/'runtime.json',cfg)
        if space_obj:space_obj.register(session,retention_family)
        session.ledger.journal('docker_create_intent',ownership=owned)
        labels=['--label',SESSION_LABEL+'='+cfg['test_session_id'],'--label',INSTANCE_LABEL+'='+instance]
        try:
            docker('volume','create',*labels,volume)
            if operation:
                from .storage_reservations import _TEST_OPERATION_HOOK
                if _TEST_OPERATION_HOOK:_TEST_OPERATION_HOOK('create_volume_created',operation)
            owned['container_id']=docker('run','-d','--name',name,*labels,
                '--memory=512m','--cpus=1','--pids-limit=128','--pull=never',
                '--env-file',env,'-p','127.0.0.1::5432',
                '--mount','type=volume,source='+volume+',target=/var/lib/postgresql/data',image).decode().strip()
            session.update(docker=owned)
            port=docker('port',owned['container_id'],'5432/tcp').decode().strip().rsplit(':',1)[1]
            cfg['dsn']=f'host=127.0.0.1 port={port} dbname={cfg["database"]} user=postgres password={password} connect_timeout=2'
            atomic_json(root/'runtime.json',cfg)
            import psycopg
            for _ in range(100):
                try:
                    with psycopg.connect(cfg['dsn']):break
                except psycopg.OperationalError:time.sleep(.2)
            else:raise StorageError('STORAGE_DATABASE','Owned PostgreSQL did not become available')
            from .store import initialize
            initialize(cfg)
            from .trusted_qa import trusted_implementation
            session.update(baseline={'trusted_implementation':trusted_implementation(),
                'executor_image':executor,'postgres_image':image,
                'source_implementation':{p.name:sha(p) for p in Path(__file__).parent.glob('*.py')}})
            session.ledger.external('container',identity=owned['container_id'],metadata=owned)
            session.ledger.external('database_volume',identity=volume,metadata=owned)
            session.update(state='running')
            session.ledger.journal('docker_created',ownership=owned)
            if space_obj:space_obj.update(session)
            return session
        except BaseException:
            session.update(state='creation_interrupted')
            # Recovery uses the persisted exact intent/labels; not an rm prefix scan.
            raise

    def update(self, **fields):
        path=self.ledger.home/'session.json'
        manifest=json.loads(path.read_text());manifest.update(fields,updated_at=now())
        atomic_json(path,manifest)
        self.ledger.session=manifest

    def own(self):
        receipt=json.loads((self.ledger.home/'session.json').read_text())['docker']
        if not receipt: raise StorageError('STORAGE_OWNER','No exclusive database receipt')
        from .storage_lifecycle import validate_managed
        validate_managed(self.cfg)
        actual=json.loads(docker('inspect',receipt['container_id'] or receipt['name']))[0]
        labels=actual['Config'].get('Labels') or {}
        expected={SESSION_LABEL:self.cfg['test_session_id'],INSTANCE_LABEL:self.cfg['instance_id']}
        if any(labels.get(k)!=v for k,v in expected.items()) or actual['Name'].lstrip('/')!=receipt['name']:
            raise StorageError('STORAGE_OWNER','Database ownership labels differ')
        if receipt['container_id'] and actual['Id']!=receipt['container_id']:
            raise StorageError('STORAGE_OWNER','Database container was replaced')
        mounts=actual['Mounts']
        if len(mounts)!=1 or mounts[0]['Type']!='volume' or mounts[0]['Name']!=receipt['volume'] or mounts[0]['Destination']!='/var/lib/postgresql/data':
            raise StorageError('STORAGE_SHARED','Only the exact exclusive PGDATA mount is supported')
        volume=json.loads(docker('volume','inspect',receipt['volume']))[0]
        if any((volume.get('Labels') or {}).get(k)!=v for k,v in expected.items()):
            raise StorageError('STORAGE_SHARED','Volume has no matching exclusive ownership')
        users=docker('ps','-a','--filter','volume='+receipt['volume'],'--format','{{.ID}}').decode().split()
        if len(users)!=1 or not actual['Id'].startswith(users[0]):
            raise StorageError('STORAGE_SHARED','Another container references this database volume')
        if actual['Image']!=receipt['image']:
            raise StorageError('STORAGE_OWNER','Database image changed')
        return receipt,actual,volume

    def query_snapshot(self):
        from .store import connect
        import hashlib
        with connect(self.cfg) as conn, conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            tables=conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
            summary={}
            for row in tables:
                table=row['tablename']
                if not table.replace('_','').isalnum():raise StorageError('STORAGE_TABLE','Unexpected table name')
                values=conn.execute('SELECT row_to_json(t) AS row FROM "'+table+'" t').fetchall()
                content=sorted(json.dumps(r['row'],sort_keys=True,default=str,separators=(',',':')) for r in values)
                summary[table]={'count':len(values),'sha256':hashlib.sha256('\n'.join(content).encode()).hexdigest()}
            release=conn.execute('SELECT release_id FROM current_release').fetchone()
            names=conn.execute('SELECT datname FROM pg_database WHERE NOT datistemplate').fetchall()
            return {'tables':summary,'current_release':str(release['release_id']) if release else None,
                    'databases':sorted(r['datname'] for r in names),
                    'queries':{'canonical_summary':conn.execute('SELECT count(*) AS crashes,count(distinct b.source_id) AS sources FROM canonical_crash c JOIN batches b ON b.id=c.batch_id').fetchone()}}

    def finish(self, *, success, failure_fingerprint=None):
        """Always stop own server; a blocked maintenance never changes job results."""
        tick=time.monotonic();receipt,actual,_=self.own()
        try:
            if not success and failure_fingerprint is None:
                failure_fingerprint=self.failure_identity()
            with maintenance(self.cfg) as (ledger,conn):
                snapshot=reference_snapshot(conn,ledger.root)
                if snapshot['active']:
                    raise StorageError('STORAGE_RECOVERABLE','Active/needs_input jobs retain their complete environment')
                if json.loads((ledger.home/'session.json').read_text()).get('processes'):
                    raise StorageError('STORAGE_PROCESS','Registered API/worker must be stopped before finalization')
                from .upload_gc import reconcile
                # GC runs later after releasing these non-reentrant maintenance locks.
                input_set=sorted({f['sha256'] for row in conn.execute('SELECT files FROM jobs').fetchall() for f in row['files']})
                self.update(state='quiescing',success=success,failure_fingerprint=failure_fingerprint,input_set=input_set)
            if self.cfg.get('storage_features',True):
                from .upload_gc import reconcile
                atomic_json(self.ledger.home/'upload-gc-finalize.json',reconcile(self.cfg,apply=True))
            from .storage_lifecycle import plan
            from .storage_archive import apply
            if self.cfg.get('storage_features',True) and not self.cfg['storage_policy'].get('keep_full'):
                reclaim_plan=plan(self.cfg)
                atomic_json(self.ledger.home/'finalize-plan.json',reclaim_plan)
                reclaimed=apply(self.cfg,reclaim_plan['id'])
                atomic_json(self.ledger.home/'finalize-resources.json',reclaimed)
            atomic_json(self.ledger.home/'database-before-stop.json',self.query_snapshot())
            docker('stop','--time','30',actual['Id'])
            self.update(state='retained',closed_at=now(),maintenance_seconds=time.monotonic()-tick)
            self.ledger.journal('session_finalized',success=success,seconds=time.monotonic()-tick)
            self.apply_retention()
        except Exception as exc:
            self.update(state='blocked',maintenance_code=getattr(exc,'code','STORAGE_FINALIZE'))
            self.ledger.journal('maintenance_blocked',code=getattr(exc,'code','STORAGE_FINALIZE'))
            # Stopping a test server retains all bytes and restores no old job.
            # Do not kill an active registered worker or executor here.
            if actual['State']['Running'] and getattr(exc,'code',None) not in {
                'STORAGE_WORKER_BUSY','STORAGE_UPLOAD_BUSY','STORAGE_PROCESS','STORAGE_BUSY'}:
                docker('stop','--time','30',actual['Id'])
            return {'status':'blocked','code':getattr(exc,'code','STORAGE_FINALIZE')}
        return {'status':'retained','seconds':time.monotonic()-tick}

    def failure_identity(self):
        from .store import connect
        from .trusted_qa import trusted_implementation, semantic_contract
        import hashlib
        with connect(self.cfg) as conn:
            jobs=conn.execute('SELECT stage,error,files,result FROM jobs ORDER BY created_at').fetchall()
            sessions=conn.execute('SELECT checkpoint FROM agent_sessions ORDER BY created_at').fetchall()
        inputs=sorted({f['sha256'] for row in jobs for f in row['files']})
        errors=sorted({(row['stage'],(row['error'] or {}).get('code'),(row['error'] or {}).get('type'))
                       for row in jobs if row['error']},key=repr)
        contracts=[];adapters=[]
        for row in sessions:
            checkpoint=row['checkpoint']
            if checkpoint.get('contract'):contracts.append(semantic_contract(checkpoint['contract']))
            if checkpoint.get('code'):adapters.append(hashlib.sha256(checkpoint['code'].encode()).hexdigest())
        identity={'version':VERSION,'suite':self.ledger.session['suite'],'errors':errors,
                  'inputs':inputs,'contracts':contracts,'adapters':sorted(adapters),
                  'trusted_implementation':trusted_implementation()}
        # No data error evidence: don't merge unrelated harness failures merely
        # because the same generic exception text appeared.
        if not errors:identity['unclassified_session']=self.cfg['test_session_id']
        return hashlib.sha256(json.dumps(identity,sort_keys=True,default=str).encode()).hexdigest()

    def apply_retention(self):
        """Only sibling sessions bearing this version's complete marker qualify."""
        if self.cfg.get('storage_space'):
            from .storage_catalog import TestSpace
            return TestSpace(self.cfg['storage_space']).retain(self)
        catalog=[]
        for path in self.ledger.home.parent.glob('*/session.json'):
            try:
                item=json.loads(path.read_text())
                if item.get('version')!=VERSION or item.get('purpose')!=self.cfg['purpose']:continue
                if item.get('suite')!=self.ledger.session['suite'] or item.get('state')!='retained':continue
                if item.get('baseline')!=self.ledger.session.get('baseline') or item.get('input_set')!=self.ledger.session.get('input_set'):continue
                candidate_cfg=json.loads((path.parent/'lab/runtime.json').read_text())
                Ledger(candidate_cfg)  # validates root, identity and policy, not mode alone
                catalog.append((path.parent,item,candidate_cfg))
            except (OSError,ValueError,StorageError):continue
        catalog.sort(key=lambda row:row[1]['created_at'])
        successes=[r for r in catalog if r[1].get('success')]
        keep={str(r[0]) for r in successes[-int(self.cfg['storage_policy'].get('expanded_successes',2)):]}
        failed={}
        for row in catalog:
            if not row[1].get('success'):
                failed.setdefault(row[1].get('failure_fingerprint') or row[1]['test_session_id'],[]).append(row)
        for group in failed.values():keep.update((str(group[0][0]),str(group[-1][0])))
        for home,manifest,cfg in catalog:
            if str(home) in keep or manifest['policy'].get('keep_full'):
                continue
            session=TestSession(cfg)
            # Published files remain expanded and referenced; only the exclusive
            # cold DB is archived. No historical release/batch is discarded.
            if any(r['pin'] for r in session.ledger.resources()):continue
            try:session.archive_database()
            except Exception as exc:
                session.update(state='blocked',maintenance_code=getattr(exc,'code','STORAGE_ARCHIVE'))

    def archive_database(self):
        from contextlib import nullcontext
        from .storage_catalog import TestSpace
        peak=nullcontext()
        if self.cfg.get('storage_space'):
            from .storage_reservations import intent
            space=TestSpace(self.cfg['storage_space'])
            receipt=json.loads((self.ledger.home/'session.json').read_text())['docker']
            op=intent(space,'backup',self.cfg['instance_id'],self.cfg['test_session_id'],self.ledger.home,receipt)
            peak=space.peak(512*1024**2,'cold backup peak',operation=op)
        with peak, self.ledger.lock():
            receipt,actual,volume=self.own()
            if actual['State']['Running'] or actual['State']['ExitCode']!=0:
                raise StorageError('STORAGE_UNCLEAN','Database must have exited normally')
            manifest=json.loads((self.ledger.home/'session.json').read_text())
            if manifest['state'] not in {'retained','db_archiving','db_verified','db_eviction_pending'}:
                raise StorageError('STORAGE_SESSION','Database session is not safely finalized')
            if manifest['policy'].get('keep_full') or manifest.get('pin') or manifest.get('lease') or any(r['pin'] for r in self.ledger.resources()):
                raise StorageError('STORAGE_PIN','Database has current keep/pin/lease protection')
            snapshot=json.loads((self.ledger.home/'database-before-stop.json').read_text())
            if set(snapshot.get('databases',[]))!={'postgres',self.cfg['database']}:
                raise StorageError('STORAGE_SHARED','Multiple test databases share this container; whole-volume eviction refused')
            differences=docker('diff',actual['Id']).decode().splitlines()
            allowed=('/run','/var/run','/tmp')
            if any(not any(line[2:]==p or line[2:].startswith(p+'/') for p in allowed) for line in differences):
                raise StorageError('STORAGE_CONTAINER_LAYER','Unexplained database container layer changes')
            atomic_json(self.ledger.home/'container-private.json',actual)
            atomic_json(self.ledger.home/'volume-private.json',volume)
            (self.ledger.home/'postgres.log').write_bytes(docker('logs',actual['Id']))
            os.chmod(self.ledger.home/'postgres.log',0o600)
            control=self.run_helper(receipt['image'],[{'type':'volume','source':receipt['volume'],
                'target':'/var/lib/postgresql/data','readonly':True}],'pg_controldata',['/var/lib/postgresql/data'],caps=['DAC_OVERRIDE'],operation_id=op['operation_id'] if self.cfg.get('storage_space') else None).decode()
            if not any('Database cluster state:' in line and line.split(':',1)[1].strip()=='shut down' for line in control.splitlines()):
                raise StorageError('STORAGE_UNCLEAN','PostgreSQL control file does not prove a clean shutdown')
            atomic_json(self.ledger.home/'cluster-control.json',{'output':control})
            archive=self.ledger.home/'archives'/'database.tar.gz'
            if archive.exists():
                verified=verify(archive)
                proof=json.loads((self.ledger.home/'database-archive.json').read_text())
                if sha(archive)!=proof['sha256']:raise StorageError('ARCHIVE_CHANGED','Database archive changed')
            else:
                assert_budget(self.ledger,512*1024**2,space_reserved=bool(self.cfg.get('storage_space')))
                self.update(state='db_archiving')
                self.ledger.journal('database_archive_intent',ownership=receipt)
                archive.parent.mkdir(exist_ok=True,mode=0o700)
                # The helper runs trusted CURRENT host modules, no uploaded code.
                package=Path(__file__).resolve().parent.parent
                code='from arsia_pipeline.storage_archive import create;create("/data","/out/database.tar.gz",context='+repr({'session_id':self.cfg['test_session_id'],'database':self.cfg['database']})+')'
                self.run_helper(receipt['executor_image'],[
                    {'type':'volume','source':receipt['volume'],'target':'/data','readonly':True},
                    {'type':'bind','source':str(archive.parent),'target':'/out','readonly':False},
                    {'type':'bind','source':str(package),'target':'/code','readonly':True}],
                    'python',['-B','-c',code],caps=['DAC_OVERRIDE'],timeout=120,operation_id=op['operation_id'] if self.cfg.get('storage_space') else None)
                verified=verify(archive)
                atomic_json(self.ledger.home/'database-archive.json',{'manifest':verified,'sha256':sha(archive),
                    'image':receipt['image'],'ownership':receipt,'verified_at':now()})
            self.update(state='db_verified');self.ledger.journal('database_verified',sha256=sha(archive))
            if self.cfg.get('storage_space'):
                from .storage_reservations import _TEST_OPERATION_HOOK
                if _TEST_OPERATION_HOOK:_TEST_OPERATION_HOOK('backup_verified',op)
            self.ledger.archive_record('database',archive)
            # Ownership and complete archive are rechecked immediately before removal.
            self.own();verify(archive,expected=verified)
            self.update(state='db_eviction_pending')
            docker('rm',actual['Id'])
            docker('volume','rm',receipt['volume'])
            self.ledger.state('container-'+receipt['container_id'],'archived',archive_id='database')
            self.ledger.state('database_volume-'+receipt['volume'],'archived',archive_id='database')
            self.update(state='archived',database_archive='archives/database.tar.gz')
            self.ledger.journal('database_archived',sha256=sha(archive))
            return verified

    def reconcile_database_eviction(self,*,locked=False):
        """Resume ONLY deletion already authorized by a complete cold backup."""
        with nullcontext() if locked else self.ledger.lock():
            manifest=json.loads((self.ledger.home/'session.json').read_text())
            if manifest['state']!='db_eviction_pending':
                raise StorageError('STORAGE_SESSION','No pending cold-database eviction to reconcile')
            archive=self.ledger.home/'archives/database.tar.gz'
            proof=json.loads((self.ledger.home/'database-archive.json').read_text())
            if sha(archive)!=proof['sha256']:raise StorageError('ARCHIVE_CHANGED','Interrupted backup changed')
            verify(archive,expected=proof['manifest'])
            receipt=proof['ownership']
            from .storage_restore import inspect_optional
            actual=inspect_optional('container',receipt.get('container_id') or receipt['name'])
            if actual is not None:
                self.own()
                if actual['State']['Running'] or actual['State']['ExitCode']!=0:
                    raise StorageError('STORAGE_UNCLEAN','Interrupted database is running or unclean')
                docker('rm',actual['Id'])
            volume=inspect_optional('volume',receipt['volume'])
            if volume is not None:
                labels=volume.get('Labels') or {}
                if labels.get(SESSION_LABEL)!=self.cfg['test_session_id'] or labels.get(INSTANCE_LABEL)!=self.cfg['instance_id']:
                    raise StorageError('STORAGE_OWNER','Pending volume ownership changed')
                if docker('ps','-a','--filter','volume='+receipt['volume'],'--format','{{.ID}}').decode().strip():
                    raise StorageError('STORAGE_SHARED','Pending volume acquired a new container reference')
                docker('volume','rm',receipt['volume'])
            self.update(state='archived',database_archive='archives/database.tar.gz')
            self.ledger.state('container-'+receipt['container_id'],'archived',archive_id='database')
            self.ledger.state('database_volume-'+receipt['volume'],'archived',archive_id='database')
            self.ledger.journal('database_eviction_reconciled')
            return {'status':'archived'}

    def recover_helpers(self):
        from .trusted_helpers import recover
        return recover(self,docker)

    def run_helper(self,image,mounts,entrypoint,args,*,caps=(),timeout=60,operation_id=None):
        from .trusted_helpers import run
        return run(self,docker,image,mounts,entrypoint,args,caps=caps,timeout=timeout,operation_id=operation_id)

    def resume_closed_maintenance(self):
        """Explicit operator recovery; never restarts a job or the old server."""
        with self.ledger.lock():
            manifest=json.loads((self.ledger.home/'session.json').read_text())
            if manifest['state']!='blocked' or not (self.ledger.home/'database-before-stop.json').is_file():
                raise StorageError('STORAGE_SESSION','No finalized maintenance checkpoint is available')
            _,actual,_=self.own()
            if actual['State']['Running'] or actual['State']['ExitCode']!=0:
                raise StorageError('STORAGE_UNCLEAN','Explicit recovery requires a closed owned server')
            self.ledger.journal('closed_maintenance_resume',previous_code=manifest.get('maintenance_code'))
            self.update(state='retained',maintenance_code=None)
        self.apply_retention()
        return {'state':json.loads((self.ledger.home/'session.json').read_text())['state']}

    def reconcile_creation(self):
        with self.ledger.lock():
            manifest=json.loads((self.ledger.home/'session.json').read_text())
            if manifest['state'] not in {'creating','creation_interrupted'}:
                raise StorageError('STORAGE_SESSION','No interrupted creation intent')
            self.recover_helpers()
            receipt=manifest['docker']
            from .storage_restore import inspect_optional
            actual=inspect_optional('container',receipt.get('container_id') or receipt['name'])
            if actual is not None:
                _,actual,_=self.own()
                receipt['container_id']=actual['Id']
                if actual['State']['Running']:docker('stop','--time','30',actual['Id'])
                self.update(docker=receipt,state='creation_interrupted',maintenance_code='CREATION_PRESERVED')
            self.ledger.journal('creation_reconciled',container_found=actual is not None,destructive_cleanup=False)
            return {'status':'blocked','code':'CREATION_PRESERVED','originals_retained':True}

    def restore_database(self, *, purpose='restore_for_use', keep=False, pin=None, hook=None):
        from .storage_restore import RestoreOperation
        return RestoreOperation(self).start(purpose=purpose,keep=keep,pin=pin,hook=hook)

    def reconcile_restore(self, operation_id, hook=None):
        from .storage_restore import RestoreOperation
        return RestoreOperation(self).reconcile(operation_id,hook=hook)
