"""One frozen bounded storage batch; production defects are preserved, never fixed here."""
import argparse
import importlib.util
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from arsia_pipeline.storage_lifecycle import StorageError, atomic_json, sha, now, maintenance
from arsia_pipeline.storage_catalog import TestSpace
from arsia_pipeline.test_session import TestSession, docker
from arsia_pipeline.storage_restore import RestoreOperation, inspect_optional
from arsia_pipeline import upload_gc, input_store, store
from storage_hardening_harness import (PROJECT_ROOT, Steps, Children, PHASES, remaining,
    require_venv, sql_files, validate_receipt, load_internal_receipt, stop_owned_session)
from verify_storage_isolated import workload, configure

IMAGE = 'arsia-import-adapter:closeout-20261002'
PG_IMAGE = 'sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67'


def main(a):
    require_venv()
    started = time.monotonic()
    deadline = started + 1500
    if a.deadline:
        deadline = min(deadline, started + (datetime.fromisoformat(a.deadline) - datetime.now(timezone.utc)).total_seconds())
    remaining(deadline)  # before output, catalog or child creation
    out = a.output.absolute(); source = a.source.absolute(); recipe = a.recipe.absolute()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    atomic_json(out/'START.json', {'at':now(), 'deadline':a.deadline, 'window_seconds':1500,
                                'data_model_calls_allowed':0, 'dependencies':{
                                    'A':'fixed local fixture', 'B':'A', 'C':'B verified archive',
                                    'D':'independent new fault suite; no B/C dependency',
                                    'C-negative':'original B archive, independent of C idempotent cleanup'}})
    steps = Steps(out, deadline); children = Children(out/'children', deadline)
    sessions = []; spaces = []; blocks = []; errors = []; imported = None
    def step(name, fn): return steps.run(name, fn)
    def attempt(name, fn, category='production implementation defect'):
        try: return step(name, fn)
        except Exception as exc:
            blocks.append({'name':name, 'category':category, 'type':type(exc).__name__,
                           'code':getattr(exc,'code',None), 'message':str(exc), 'at':now()})
            atomic_json(out/'blocked.json', blocks)
            if getattr(exc,'code',None) in {'STORAGE_OWNER','STORAGE_SHARED','STORAGE_CATALOG'}:
                raise  # unknown ownership: entire destructive batch stops
            return None
    def fresh(space, suite, relative):
        remaining(deadline)
        s = TestSession.create(space.root/relative, suite=suite, postgres_image=PG_IMAGE,
                               executor_image=IMAGE, space=space.root)
        sessions.append(s); configure(s)
        return s
    def client(s):
        configure(s); from arsia_pipeline import api
        return TestClient(api.app)
    def job(c, name):
        remaining(deadline); r=c.post('/jobs',json={'label':name});r.raise_for_status();return r.json()['id']
    def cancel(c,jid): c.post('/jobs/'+jid+'/cancel').raise_for_status()
    def upload(s,c,jid,data,name):
        r=c.put('/jobs/'+jid+'/files',params={'filename':name},content=data);r.raise_for_status()
        files=r.json()['files'];assert all('path' not in f for f in files)
        public=next(f for f in files if f['name']==name)
        receipt=load_internal_receipt(s,jid,public)
        assert input_store.resolve(s.cfg,receipt).read_bytes()==data
        return receipt
    def fresh_gc(s):
        return children.finish(children.spawn(s,'gc'))
    def restore_checks(s,op,digest):
        expected=json.loads((s.ledger.home/'database-before-stop.json').read_text())
        assert op['validation_result']=='pass' and op['all_members_verified']
        assert op['tables']==expected['tables'] and op['queries']['current_release']==expected['current_release']
        assert op['queries']['canonical_summary']==expected['queries']['canonical_summary']
        assert op['tables']['canonical_crash']['count']==632
        assert sha(s.ledger.home/'archives/database.tar.gz')==digest
        return expected
    def absent(op):
        assert inspect_optional('container',op['name']) is None
        assert inspect_optional('volume',op['volume']) is None
    try:
        space=TestSpace.create(out/'space');spaces.append(space)
        holder={}
        def A():
            s,result=workload(space.root/'run-a/published', source, json.loads(recipe.read_text()),
                IMAGE,True,deadline,imports=3,space=space.root,
                filenames=[source.name,source.name,'renamed-identical'+source.suffix])
            sessions.append(s);holder.update(session=s,result=result)
            assert json.loads((s.ledger.home/'storage-finalize.json').read_text())['status']=='retained'
            return result
        imported=attempt('A-H13-normal-import',A,'acceptance pathway or environment')
        published=holder.get('session')
        if imported:
            def oracle():
                path=PROJECT_ROOT/'artifacts/closeout-20261002/tas_oracle.py'
                spec=importlib.util.spec_from_file_location('tas_oracle',path)
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                runs=[json.loads(p.read_text()) for p in (published.ledger.root/'attempts'/imported['uploads'][0]['job_id']).glob('*/agent/run-*/execution.json')]
                full=next(x for x in runs if x['mode']=='full')
                proof=module.verify(source,Path(full['output_dir'])/'crashes.jsonl',json.loads((published.ledger.home/'query.json').read_text()))
                assert proof['passed'];return proof
            attempt('A-independent-oracle',oracle,'independent business verification')
            def B():
                b=fresh(space,'same-bytes-ten-upload-v1','run-b/small');c=client(b)
                jid=job(c,'synthetic beta');upload(b,c,jid,b'id,label\nb,beta\n','beta.csv');cancel(c,jid)
                assert b.finish(success=True)['status']=='retained'
                space.pin(published.cfg['test_session_id'],'bounded retention protection')
                d=fresh(space,'same-bytes-ten-upload-v1','run-c/small');c=client(d)
                jid=job(c,'synthetic gamma');upload(d,c,jid,b'id,label\nc,gamma\n','gamma.csv');cancel(c,jid)
                assert d.finish(success=True)['status']=='retained'
                assert json.loads((published.ledger.home/'session.json').read_text())['state']=='retained'
                identities=[json.loads((s.ledger.home/'session.json').read_text()) for s in (published,b,d)]
                assert len({tuple(m['input_set']) for m in identities})==3
                assert all(m['baseline']==identities[0]['baseline'] for m in identities)
                space.pin(published.cfg['test_session_id'],None)
                p=children.spawn(d,'retention','retention_claimed')
                second=children.finish(children.spawn(d,'retention'))
                assert any(x['status']=='deferred' for x in second)
                first=children.finish(p)
                states=[json.loads((s.ledger.home/'session.json').read_text())['state'] for s in (published,b,d)]
                assert states==['archived','retained','retained']
                assert any(x['status']=='archived' for x in first)
                archive=published.ledger.home/'archives/database.tar.gz'
                proof=json.loads((published.ledger.home/'database-archive.json').read_text())
                assert sha(archive)==proof['sha256']
                return {'states':states,'pin_protected_oldest':True,'input_sets':[m['input_set'] for m in identities],
                        'baselines_equal':True,'first_finalizer':first,'second_finalizer':second,
                        'n':space.marker['policy']['expanded_successes'],'archive_sha256':sha(archive)}
            retention=attempt('B-H05-H07-retention',B)
            if retention:
                digest=retention['archive_sha256']
                def C():
                    op=children.finish(children.spawn(published,'restore'))
                    atomic_json(out/'restore-returned.json',op)
                    restore_checks(published,op,digest)
                    assert op['state']=='reclaimed';absent(op)
                    return op
                restored=attempt('C-H01-H14-verify-and-reclaim',C)
                if restored:
                    for phase in ('restore_verified','restore_container_removed'):
                        def interrupted(phase=phase):
                            p=children.spawn(published,'restore',phase)
                            opid=p['receipt']['operation_id'];killed=children.finish(p,kill=True)
                            before=published.ledger.get_operation(opid)
                            atomic_json(out/(phase+'-postkill.json'),before)
                            values=[]
                            for repetition in range(2):
                                reconciliation=children.finish(children.spawn(published,'reconcile-reservations'))
                                assert reconciliation['active_bytes']==0, reconciliation
                                value=children.finish(children.spawn(published,'reconcile-restore',operation=opid))
                                value['reservation_reconciliation']=reconciliation
                                values.append(value);atomic_json(out/(phase+'-reconcile.json'),values)
                                assert value['state']=='reclaimed'
                            restore_checks(published,values[-1],digest);absent(values[-1])
                            return {'kill':killed,'reconciled_twice':values,'archive_sha256':digest}
                        attempt('C-H04-'+phase,interrupted)
                def retained():
                    values=[]
                    for phase in ('restore_reserved','restore_volume_created','restore_container_created'):
                        p=children.spawn(published,'restore',phase);opid=p['receipt']['operation_id']
                        killed=children.finish(p,kill=True)
                        rounds=[children.finish(children.spawn(published,'reconcile-reservations')) for _ in range(2)]
                        assert all(x['active_bytes']==0 for x in rounds),rounds
                        value=published.ledger.get_operation(opid)
                        assert value['state']=='blocked'
                        assert (inspect_optional('volume',value['volume']) is not None)==(phase!='restore_reserved')
                        c=inspect_optional('container',value['name']);assert c is None or not c['State']['Running']
                        assert sha(published.ledger.home/'archives/database.tar.gz')==digest
                        values.append({'kill':killed,'operation':value,'reservation_reconciliations':rounds});atomic_json(out/'unverified-interruptions.json',values)
                    op=children.finish(children.spawn(published,'restore',purpose='restore_for_use'))
                    assert op['purpose']=='restore_for_use' and op['pin'] and op['state']=='verified_retained'
                    assert not inspect_optional('container',op['name'])['State']['Running']
                    restore_checks(published,op,digest)
                    return {'unverified':values,'for_use':op}
                attempt('C-H02-unverified-and-for-use',retained)
                def pin():
                    op=children.finish(children.spawn(published,'restore',pin='bounded test pin'))
                    assert op['state']=='verified_retained' and not inspect_optional('container',op['name'])['State']['Running']
                    try:published.reconcile_restore(op['operation_id'])
                    except StorageError as exc:assert exc.code=='RESTORE_RETAINED'
                    else:raise AssertionError('Pin must prevent cleanup')
                    return {'retained':op,'pin_cleanup_refused':True}
                attempt('C-H02-pin',pin)
                def cleanup_failure():
                    op=children.finish(children.spawn(published,'restore',inject_cleanup_fault='yes'))
                    atomic_json(out/'cleanup-injection-returned.json',op)
                    assert op['validation_result']=='pass' and op['cleanup_code']=='STORAGE_TEST_CLEANUP'
                    restore_checks(published,op,digest)
                    recovered=children.finish(children.spawn(published,'reconcile-restore',operation=op['operation_id']))
                    assert recovered['state']=='reclaimed';absent(recovered)
                    return {'injected':op,'recovered':recovered,'import_jobs_unchanged':True}
                attempt('C-H15-cleanup-failure',cleanup_failure)
        if getattr(a,'sections','ABCD') == 'ABCD':
            # Independent upload suite, intentionally outside successful retention family.
            fault_space=TestSpace.create(out/'fault-space');spaces.append(fault_space)
            fault=fresh(fault_space,'upload-faults-v2','run-d/faults');c=client(fault)
            data=b'id,label\none,alpha\n';other=out/'other.csv';other.write_bytes(b'id,label\ntwo,beta\n')
            material=out/'shared.csv';material.write_bytes(data)
            jid=job(c,'successful shared reference');shared=upload(fault,c,jid,data,material.name);cancel(c,jid)
            def overlapping():
                one=job(c,'overlap one');two=job(c,'overlap two')
                overlap=out/'overlap.csv';overlap_data=b'id,label\noverlap,concurrent\n';overlap.write_bytes(overlap_data)
                p=children.spawn(fault,'upload','upload_partial',job=one,payload=overlap)
                busy=c.put('/jobs/'+two+'/files',params={'filename':'same-again.csv'},content=overlap_data)
                assert busy.status_code==409
                assert p['p'].poll() is None
                completed=children.finish(p)
                second=upload(fault,c,two,overlap_data,'same-again.csv')
                first=sql_files(fault,one)[0]
                assert first['sha256']==second['sha256'] and first['path']==second['path']
                assert first['id']!=second['id']
                cancel(c,one);cancel(c,two)
                preserved=fresh_gc(fault)
                assert input_store.resolve(fault.cfg,second).read_bytes()==overlap_data
                return {'overlapping_child':p['receipt'],'busy_status':busy.status_code,'bounded_retries':1,
                    'receipt_ids':[first['id'],second['id']],'one_blob':first['path'],'preserved_after_cancel':True,'gc':preserved}
            attempt('R06-overlapping-same-sha',overlapping)
            hard=[]
            def D():
                for phase,payload in [('upload_partial',other),('upload_pending_commit',material),('upload_sql_committed',other)]:
                    remaining(deadline);jid=job(c,phase)
                    record={'phase':phase,'job_id':jid,'expected':PHASES[phase],'status':'running'};hard.append(record)
                    atomic_json(out/'upload-hard-kills.json',hard)
                    p=children.spawn(fault,'upload',phase,job=jid,payload=payload)
                    opid=p['receipt']['operation_id'];record['operation_id']=opid
                    files=sql_files(fault,jid);assert len(files)==PHASES[phase]['sql_files']
                    op=fault.ledger.get_operation(opid)
                    record['prekill']={'sql_file_ids':[x['id'] for x in files],'operation':op}
                    atomic_json(out/'upload-hard-kills.json',hard)
                    if PHASES[phase]['check_busy']:
                        try:upload_gc.reconcile(fault.cfg,apply=True,clock=datetime.now(timezone.utc)+timedelta(days=2))
                        except StorageError as exc:
                            assert exc.code in {'STORAGE_UPLOAD_BUSY','STORAGE_WORKER_BUSY'};record['live_lock_busy']=exc.code
                        else:raise AssertionError('Live precommit upload lock must refuse GC')
                    else:
                        assert files[0]['id']==opid and op['state']=='pending_commit'
                        validate_receipt(fault,jid,files[0])
                    record['kill']=children.finish(p,kill=True)
                    atomic_json(out/'upload-hard-kills.json',hard)
                    files=sql_files(fault,jid);assert len(files)==PHASES[phase]['sql_files']
                    record['postkill']={'sql_file_ids':[x['id'] for x in files], 'operation':fault.ledger.get_operation(opid)}
                    atomic_json(out/'upload-hard-kills.json',hard)
                    with maintenance(fault.cfg):record['locks_released']=True
                    if phase=='upload_sql_committed':
                        assert record['postkill']['operation']['state']=='pending_commit'
                        reconciled=fresh_gc(fault);record['fresh_gc']=reconciled
                        atomic_json(out/'upload-hard-kills.json',hard)
                        assert any(x['id']==opid and x['action']=='committed' for x in reconciled['results'])
                        assert not any(x['action']=='reclaimed' for x in reconciled['results'])
                        assert fault.ledger.get_operation(opid)['state']=='committed'
                        assert input_store.resolve(fault.cfg,files[0]).read_bytes()==payload.read_bytes()
                        record['second_gc']=fresh_gc(fault)
                        atomic_json(out/'upload-hard-kills.json',hard)
                        assert fault.ledger.get_operation(opid)['state']=='committed'
                        cancel(c,jid)
                    else:
                        active=fresh_gc(fault);record['active_gc']=active
                        atomic_json(out/'upload-hard-kills.json',hard)
                        assert not any(x['action']=='reclaimed' for x in active['results'])
                        cancel(c,jid);record['fresh_gc']=fresh_gc(fault)
                        atomic_json(out/'upload-hard-kills.json',hard)
                        assert fault.ledger.get_operation(opid)['state']=='reclaimed'
                        assert (fault.ledger.home/'tombstones'/(opid+'.json')).is_file()
                    assert input_store.resolve(fault.cfg,shared).read_bytes()==data
                    record['status']='pass';atomic_json(out/'upload-hard-kills.json',hard)
                assert not list((fault.ledger.root/'uploads').rglob('*.part'))
                return {'windows':hard,'shared_bytes_unchanged':True,'tombstones':len(list((fault.ledger.home/'tombstones').glob('*.json')))}
            hard_result=attempt('D-H09-H11-upload-windows',D)
            if hard_result:
                def orphan():
                    unique=out/'unique.csv';unique.write_bytes(b'id,value\nunique,gamma\n');jid=job(c,'unique orphan')
                    p=children.spawn(fault,'upload','upload_pending_commit',job=jid,payload=unique)
                    opid=p['receipt']['operation_id'];killed=children.finish(p,kill=True);cancel(c,jid)
                    op=fault.ledger.get_operation(opid);blob=fault.ledger.root/'blobs/sha256'/op['sha256']/'content'
                    assert blob.exists();value=fresh_gc(fault);atomic_json(out/'unique-orphan-gc.json',value)
                    assert not blob.exists() and fault.ledger.get_operation(opid)['state']=='reclaimed'
                    assert input_store.resolve(fault.cfg,shared).read_bytes()==data
                    return {'kill':killed,'gc':value,'unique_blob_reclaimed':True}
                attempt('D-H09-unique-orphan',orphan)
                def protection():
                    unknown=fault.ledger.root/'uploads/unknown.part';unknown.write_bytes(b'unknown retained')
                    jid=job(c,'grace/checkpoint');p=children.spawn(fault,'upload','upload_partial',job=jid,payload=other)
                    opid=p['receipt']['operation_id'];killed=children.finish(p,kill=True);cancel(c,jid)
                    part=fault.ledger.root/fault.ledger.get_operation(opid)['partial']
                    recent=upload_gc.reconcile(fault.cfg,apply=True);assert part.exists()
                    from psycopg.types.json import Jsonb
                    with store.connect(fault.cfg) as conn:conn.execute('UPDATE jobs SET options=%s WHERE id=%s',(Jsonb({'checkpoint_file_id':opid}),jid))
                    checkpoint=fresh_gc(fault);assert part.exists()
                    with store.connect(fault.cfg) as conn:conn.execute("UPDATE jobs SET options='{}'::jsonb,status='needs_input' WHERE id=%s",(jid,))
                    needs=fresh_gc(fault);assert part.exists();cancel(c,jid)
                    saved=part.with_suffix('.saved');part.rename(saved);part.symlink_to(saved)
                    try:symlink=fresh_gc(fault);assert part.is_symlink()
                    finally:part.unlink();saved.rename(part)
                    bad={**fault.cfg,'dsn':'host=127.0.0.1 port=1 dbname=invalid user=invalid connect_timeout=1'}
                    try:upload_gc.reconcile(bad,apply=True)
                    except Exception as exc:assert type(exc).__name__=='OperationalError';db_error=type(exc).__name__
                    else:raise AssertionError('Unavailable DB must refuse GC')
                    assert part.exists() and unknown.exists()
                    last=fresh_gc(fault);assert not part.exists() and unknown.exists()
                    return {'kill':killed,'recent':recent,'checkpoint':checkpoint,'needs_input':needs,
                            'symlink':symlink,'db_unavailable':db_error,'last':last,'unknown_retained':True}
                attempt('D-H12-protections',protection)
            def creation_backup_boundaries():
                boundary=TestSpace.create(out/'boundary-space');spaces.append(boundary)
                parent=fresh(boundary,'boundary-anchor','anchor');parent.finish(success=True)
                results=[]
                for phase in ('create_reserved','create_volume_created'):
                    home=boundary.root/phase
                    p=children.spawn(parent,'create',phase,home=home)
                    payload=json.loads(p['result'].with_suffix('.operation-intent.json').read_text())
                    assert payload['kind']=='create' and payload['home']==str(home) and payload['space_id']==boundary.marker['space_id']
                    # A second process must not take a still-live owner's peak.
                    live=children.finish(children.spawn(parent,'reconcile-reservations'))
                    assert live['active_bytes']>0 and any(x['status']=='deferred' for x in live['results'])
                    killed=children.finish(p,kill=True)
                    rounds=[children.finish(children.spawn(parent,'reconcile-reservations')) for _ in range(2)]
                    assert all(x['active_bytes']==0 for x in rounds),rounds
                    volume=inspect_optional('volume',payload['expected']['volume'])
                    assert (volume is not None)==(phase=='create_volume_created')
                    if volume is not None:assert any(x['identity']==payload['expected']['volume'] for x in boundary.measure()['unknown_components'])
                    results.append({'phase':phase,'kill':killed,'live_owner':live,'rounds':rounds,'intent':payload})
                for phase in ('backup_reserved','backup_verified'):
                    p=children.spawn(parent,'archive',phase)
                    killed=children.finish(p,kill=True)
                    rounds=[children.finish(children.spawn(parent,'reconcile-reservations')) for _ in range(2)]
                    assert all(x['active_bytes']==0 for x in rounds),rounds
                    assert inspect_optional('volume',parent.ledger.session['docker']['volume']) is not None
                    results.append({'phase':phase,'kill':killed,'rounds':rounds})
                return results
            attempt('R04-create-backup-live-owner-boundaries',creation_backup_boundaries)
            def budget():
                low=TestSpace.create(out/'budget-space',budget_bytes=1);spaces.append(low)
                try:TestSession.create(low.root/'new/session',suite='budget',postgres_image=PG_IMAGE,executor_image=IMAGE,space=low.root)
                except StorageError as exc:assert exc.code=='STORAGE_SPACE_BUDGET'
                else:raise AssertionError('Tiny budget must reject before resource creation')
                assert not (low.root/'new/session').exists()
                values=[]
                for space in spaces:
                    with space.db() as db:
                        reservations=[dict(x) for x in db.execute("SELECT * FROM reservations WHERE state!='released'")]
                        released=[dict(x) for x in db.execute("SELECT * FROM reservations WHERE state='released'")]
                        claims=[dict(x) for x in db.execute('SELECT id,claim,claim_until FROM sessions WHERE claim IS NOT NULL')]
                    values.append({'space':str(space.root.relative_to(out)), 'measure':space.measure(),
                                   'reservations':reservations,'released_audit':released,'claims':claims})
                atomic_json(out/'reservations.json',values)
                assert all(not v['reservations'] and not v['claims'] for v in values), 'SIGKILL left production budget reservation/claim; preserved without resetting catalog'
                return {'tiny_budget_refused':True,'spaces':values}
            attempt('D-H08-budget-and-crash-reservations',budget)
            if hard_result:
                def finish_fault():
                    value=fault.finish(success=True);assert value['status']=='retained';return value
                attempt('D-fault-finalize',finish_fault)
    except BaseException as exc:
        errors.append({'type':type(exc).__name__,'code':getattr(exc,'code',None),'message':str(exc)})
        atomic_json(out/'fatal.json',errors)
    finally:
        cleanup_started=time.monotonic();until=cleanup_started+180
        child_cleanup=children.stop(allowance=60);resource_cleanup=[]
        # Discover only this run's explicitly enrolled creations, including partial create failures.
        for space in spaces:
            for row in space.rows():
                cfg,_=space.configuration(row)
                if not any(s.cfg['test_session_id']==cfg['test_session_id'] for s in sessions):sessions.append(TestSession(cfg))
        for s in sessions:
            for op in s.ledger.operations('restore'):
                try:
                    remaining(until,30);c,v=RestoreOperation(s).own(op)
                    if c and c['State']['Running']:
                        docker('stop','--time','30',c['Id']);c,v=RestoreOperation(s).own(op)
                    resource_cleanup.append({'operation':op['operation_id'],'state':op['state'],
                        'container_present':c is not None,'volume_present':v is not None,
                        'running':bool(c and c['State']['Running']), 'preserve_reason':op.get('pin') or op.get('reason') or op.get('cleanup_code')})
                except Exception as exc:
                    resource_cleanup.append({'operation':op['operation_id'],'status':'blocked','running':None,
                        'code':getattr(exc,'code',None),'error':str(exc)})
            try:
                remaining(until,30)
                manifest=json.loads((s.ledger.home/'session.json').read_text())
                if manifest['state']=='creation_interrupted' and inspect_optional('container',manifest['docker']['name']) is None:
                    resource_cleanup.append({'session':s.cfg['test_session_id'],'state':'creation_interrupted','running':False,
                        'volume':manifest['docker']['volume'],'preserve_reason':'registered diagnostic volume; reconciled peak'})
                else:resource_cleanup.append(stop_owned_session(s))
            except Exception as exc:resource_cleanup.append({'session':s.cfg['test_session_id'],'status':'blocked',
                'code':getattr(exc,'code',None),'error':str(exc),'running':None})
        cleanup={'children':child_cleanup,'resources':resource_cleanup,
                 'allowance_seconds':180,'seconds':time.monotonic()-cleanup_started,
                 'deadline_overrun_seconds':max(0,time.monotonic()-deadline)}
        atomic_json(out/'cleanup.json',cleanup)
        clean=all(x.get('stopped') for x in child_cleanup) and all(x.get('status')!='blocked' and x.get('running') is not True for x in resource_cleanup)
        atomic_json(out/'result.json',{'status':'pass' if not blocks and not errors and clean else 'partial',
            'wall_seconds':time.monotonic()-started,'steps':steps.rows,'blocks':blocks,'fatal':errors,
            'cleanup_verified':clean,'cleanup':cleanup,'data_model_calls':imported['data_model_calls'] if imported else None,
            'data_model_tokens':imported['data_model_tokens'] if imported else None,
            'limits':'fixed admitted material/adapter; no unknown-source autonomy; failed production chains not repaired'})
    return 0 if not blocks and not errors and clean else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--recipe',type=Path,required=True)
    p.add_argument('--deadline',required=True)
    p.add_argument('--sections',choices=['ABCD','ABC'],default='ABCD')
    raise SystemExit(main(p.parse_args()))
