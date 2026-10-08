"""Targeted reliability acceptance: new owned session per fault scenario."""
import argparse
import json
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi.testclient import TestClient
from arsia_pipeline import input_store,store,upload_gc
from arsia_pipeline.storage_lifecycle import atomic_json,now,sha,maintenance,StorageError
from arsia_pipeline.storage_catalog import TestSpace
from arsia_pipeline.storage_restore import inspect_optional
from arsia_pipeline.storage_reservations import status as reservation_status
from arsia_pipeline.test_session import TestSession
from storage_hardening_harness import Children,Steps,PHASES,sql_files,load_internal_receipt,stop_owned_session,PROJECT_ROOT
from verify_storage_isolated import configure,workload
PG='sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67'
IMAGE='arsia-import-adapter:closeout-20261002'


def main(a):
    out=a.output.absolute();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    deadline=time.monotonic()+(datetime.fromisoformat(a.deadline)-datetime.now(timezone.utc)).total_seconds()
    steps=Steps(out,deadline);all_sessions=[];results=[]
    def scenario(name,body):
        root=out/name;root.mkdir(mode=0o700)
        space=TestSpace.create(root/'space')
        children=Children(root/'children',deadline)
        s=TestSession.create(space.root/'session',suite=name,postgres_image=PG,executor_image=IMAGE,space=space.root)
        all_sessions.append(s);configure(s)
        from arsia_pipeline import api
        c=TestClient(api.app);owned=[]
        def job(label):
            r=c.post('/jobs',json={'label':label});r.raise_for_status();jid=r.json()['id'];owned.append(jid)
            atomic_json(root/'ownership.json',{'scenario':name,'session_id':s.cfg['test_session_id'],
                'instance_id':s.cfg['instance_id'],'home':str(s.ledger.home),'jobs':owned})
            return jid
        def cancel(jid):
            r=c.post('/jobs/'+jid+'/cancel');r.raise_for_status()
            assert r.json()['status']=='cancelled',r.json()['status']
        def upload(jid,data,filename):
            r=c.put('/jobs/'+jid+'/files',params={'filename':filename},content=data);r.raise_for_status()
            public=next(x for x in r.json()['files'] if x['name']==filename)
            f=load_internal_receipt(s,jid,public);assert input_store.resolve(s.cfg,f).read_bytes()==data
            return f
        def gc():return children.finish(children.spawn(s,'gc',scenario=name))
        with store.connect(s.cfg) as conn:
            assert conn.execute('SELECT count(*) AS n FROM jobs').fetchone()['n']==0
        with maintenance(s.cfg):pass
        atomic_json(root/'baseline.json',{'jobs':0,'resources':s.ledger.resources(),
            'uploads':list(map(str,(s.ledger.root/'uploads').glob('*'))),'locks_acquired':True,
            'budget':reservation_status(space)})
        try:
            value=body(s,c,children,space,root,job,cancel,upload,gc)
            atomic_json(root/'result.json',value)
            return value
        except BaseException as exc:
            atomic_json(root/'failure.json',{'at':now(),'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()})
            raise
        finally:
            cleanup={'children':children.stop(),'jobs':[]}
            try:
                configure(s)
                manifest=json.loads((s.ledger.home/'session.json').read_text())
                actual={'State':{'Running':False}} if manifest['state']=='archived' else s.own()[1]
                if actual['State']['Running']:
                    for jid in owned:
                        value=store.get_job(jid,internal=True)
                        if value['status'] not in {'succeeded','no_change','cancelled','failed'}:cancel(jid)
                        cleanup['jobs'].append({'id':jid,'status':store.get_job(jid,internal=True)['status']})
                    with maintenance(s.cfg):cleanup['locks_released']=True
                    cleanup['finalize']=s.finish(success=False,failure_fingerprint='acceptance-scenario-'+name)
                cleanup['stop']=stop_owned_session(s)
                cleanup['budget']=reservation_status(space)
                cleanup['measure']=space.measure()
            except BaseException as exc:cleanup['blocked']={'type':type(exc).__name__,'message':str(exc)}
            atomic_json(root/'cleanup.json',cleanup)
    def attempt(name,fn):
        try:value=steps.run(name,fn);results.append({'name':name,'status':'pass'})
        except Exception as exc:results.append({'name':name,'status':'fail','type':type(exc).__name__,'message':str(exc)})
        atomic_json(out/'results.json',results)
    def overlap(s,c,k,space,root,job,cancel,upload,gc):
        payload=root/'overlap.csv';data=b'id,value\n1,shared\n';payload.write_bytes(data)
        one,two=job('overlap one'),job('overlap two')
        p=k.spawn(s,'upload','upload_partial',job=one,payload=payload,scenario='R06')
        before=now();assert p['p'].poll() is None
        busy=c.put('/jobs/'+two+'/files',params={'filename':'renamed.csv'},content=data)
        after=now();assert busy.status_code==409;assert p['p'].poll() is None
        atomic_json(root/'overlap.json',{'request_two_started':before,'request_two_ended':after,
            'status':busy.status_code,'body':busy.json(),'first_still_waiting':True,'ready':p['receipt']['actual_barrier']})
        k.finish(p);second=upload(two,data,'renamed.csv');first=sql_files(s,one)[0]
        assert first['sha256']==second['sha256'] and first['path']==second['path'] and first['id']!=second['id']
        cancel(one);preserved=gc();assert input_store.resolve(s.cfg,second).read_bytes()==data
        cancel(two);again=gc();assert input_store.resolve(s.cfg,second).read_bytes()==data
        blobs=[r for r in s.ledger.resources() if r['kind']=='raw_blob'];assert len(blobs)==1
        return {'receipt_ids':[first['id'],second['id']],'blob':first['path'],'receipts':2,'raw_blobs':1,
            'bounded_retry':1,'busy_status':409,'gc':[preserved,again],'other_reference_preserved':True}
    def window(phase):
        def run(s,c,k,space,root,job,cancel,upload,gc):
            shared_data=b'id,value\n1,shared\n';shared=upload(job('shared reference'),shared_data,'shared.csv')
            # A committed receipt remains authoritative even after cancellation.
            cancel(shared['job_id'])
            data=shared_data if phase=='upload_pending_commit' else b'id,value\n2,interrupted\n'
            payload=root/'input.csv';payload.write_bytes(data);jid=job(phase)
            p=k.spawn(s,'upload',phase,job=jid,payload=payload,scenario=phase)
            opid=p['receipt']['operation_id'];before=s.ledger.get_operation(opid)
            assert len(sql_files(s,jid))==PHASES[phase]['sql_files']
            atomic_json(root/'prekill.json',{'operation':before,'files':sql_files(s,jid),'ready':p['receipt']['actual_barrier']})
            if PHASES[phase]['check_busy']:
                try:upload_gc.reconcile(s.cfg,apply=True,clock=datetime.now(timezone.utc)+timedelta(days=2))
                except StorageError as exc:assert exc.code in {'STORAGE_UPLOAD_BUSY','STORAGE_WORKER_BUSY'}
                else:raise AssertionError('Live upload must exclude GC')
            killed=k.finish(p,kill=True)
            with maintenance(s.cfg):pass
            files=sql_files(s,jid);assert len(files)==PHASES[phase]['sql_files']
            atomic_json(root/'postkill.json',{'operation':s.ledger.get_operation(opid),'files':files,'kill':killed,'locks_released':True})
            first=gc();atomic_json(root/'first-reconcile.json',first)
            if phase=='upload_sql_committed':
                assert any(x['id']==opid and x['action']=='committed' for x in first['results'])
                assert s.ledger.get_operation(opid)['state']=='committed'
                assert input_store.resolve(s.cfg,files[0]).read_bytes()==data
                second=gc();assert s.ledger.get_operation(opid)['state']=='committed';cancel(jid)
                state='committed_preserved'
            else:
                assert not any(x['action']=='reclaimed' for x in first['results'])
                cancel(jid);second=gc();atomic_json(root/'after-cancel-reconcile.json',second)
                assert s.ledger.get_operation(opid)['state']=='reclaimed'
                assert (s.ledger.home/'tombstones'/(opid+'.json')).is_file()
                state='reclaimed_after_cancel'
            third=gc();assert input_store.resolve(s.cfg,shared).read_bytes()==shared_data
            assert not list((s.ledger.root/'uploads').rglob('*.part'))
            return {'phase':phase,'kill':killed,'outcome':state,'reconciliations':[first,second,third],
                'final_operation':s.ledger.get_operation(opid),'shared_reference_preserved':True,'locks_released':True}
        return run
    def restore(s,c,k,space,root,job,cancel,upload,gc):
        upload_id=job('archive seed');upload(upload_id,b'id,value\n1,archive\n','seed.csv');cancel(upload_id)
        assert s.finish(success=True)['status']=='retained'
        archived=k.finish(k.spawn(s,'archive',scenario='R04-restore'))
        assert json.loads((s.ledger.home/'session.json').read_text())['state']=='archived'
        assert archived==json.loads((s.ledger.home/'database-archive.json').read_text())['manifest']
        digest=sha(s.ledger.home/'archives/database.tar.gz')
        p=k.spawn(s,'restore','restore_container_created',scenario='R04-restore')
        before=reservation_status(space)
        live=k.finish(k.spawn(s,'reconcile-reservations',scenario='R04-restore'))
        after=reservation_status(space)
        assert p['p'].poll() is None and live['active_bytes']>0
        assert any(x['status']=='deferred' for x in live['results'])
        assert before['records']==after['records'], 'Live owner reservation changed'
        restored=k.finish(p);assert restored['validation_result']=='pass' and restored['state']=='reclaimed'
        rounds=[k.finish(k.spawn(s,'reconcile-reservations',scenario='R04-restore')) for _ in range(2)]
        assert all(x['active_bytes']==0 for x in rounds)
        assert inspect_optional('container',restored['name']) is None and inspect_optional('volume',restored['volume']) is None
        assert sha(s.ledger.home/'archives/database.tar.gz')==digest
        return {'before':before,'live_reconciler':live,'after':after,'restore':restored,'rounds':rounds,'archive_sha256':digest}
    def backup(s,c,k,space,root,job,cancel,upload,gc):
        jid=job('backup seed');upload(jid,b'id,value\n1,backup\n','seed.csv');cancel(jid)
        assert s.finish(success=True)['status']=='retained'
        p=k.spawn(s,'archive-live-helper','backup_helper_running',scenario='R04-backup')
        helper=json.loads(p['result'].with_suffix('.live-helper.json').read_text())
        actual=inspect_optional('container',helper['intent']['name']);assert actual['State']['Running']
        atomic_json(root/'helper-before.json',actual)
        before=reservation_status(space);assert before['active_bytes']>0
        killed=k.finish(p,kill=True)
        actual=inspect_optional('container',helper['intent']['name']);assert actual['State']['Running']
        atomic_json(root/'helper-after-host-kill.json',actual)
        rounds=[k.finish(k.spawn(s,'reconcile-reservations',scenario='R04-backup')) for _ in range(2)]
        atomic_json(root/'reconcile.json',rounds)
        assert all(x['active_bytes']==0 for x in rounds),rounds
        assert inspect_optional('container',helper['intent']['name']) is None
        _,actual,volume=s.own();assert not actual['State']['Running']
        measured=space.measure();assert measured['docker_reserved_bytes']>0 and any(x['identity']==volume['Name'] for x in measured['unknown_components'])
        return {'kill':killed,'helper':helper,'before':before,'rounds':rounds,'retained_volume':volume['Name'],'measure':measured}
    selected=a.scenarios.split(',')
    if 'R06' in selected:attempt('R06',lambda:scenario('R06',overlap))
    if 'R08' in selected:
        for phase in PHASES:attempt('R08-'+phase,lambda phase=phase:scenario('R08-'+phase,window(phase)))
    if 'R04' in selected or 'restore' in selected:
        attempt('R04-live-restore',lambda:scenario('R04-live-restore',restore))
    if 'R04' in selected or 'backup' in selected:
        attempt('R04-live-backup',lambda:scenario('R04-live-backup',backup))
    if 'normal' in selected:
        def normal():
            space=TestSpace.create(out/'normal-space')
            source=PROJECT_ROOT/'artifacts/tas-isolated-20261002-0458/downloads/TAS_Crashes_2024_01.geojson'
            recipe=PROJECT_ROOT/'artifacts/closeout-20261002/real-import/recipes/cf7570d4f654b9b802765b6f03aaf19e9f1928519eac5bb42aa5d26bd01803a8/objects/12496d636c1c32a0b8a8769e0a126e3c1f52a700a420f328d9245b5432f69fad'
            s,value=workload(space.root/'session',source,json.loads(recipe.read_text()),IMAGE,True,deadline,
                imports=3,space=space.root,filenames=[source.name,source.name,'renamed.geojson'])
            all_sessions.append(s);return value
        attempt('normal',normal)
    atomic_json(out/'sessions.json',[{'home':str(s.ledger.home),'id':s.cfg['test_session_id']} for s in all_sessions])
    return int(any(x['status']!='pass' for x in results))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--deadline',required=True)
    p.add_argument('--scenarios',default='R06,R08,R04,normal');raise SystemExit(main(p.parse_args()))
