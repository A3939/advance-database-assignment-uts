"""Bounded storage workload using the existing controlled acceptance pathway.

Known admitted recipe is fixture material, NOT an inherited admission token.
First upload gets fresh sample/full QA and normal registration. Repetitions run
the real worker and recipe reader with fresh QA. No model or network fallback.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

from arsia_pipeline.test_session import TestSession
from arsia_pipeline.storage_lifecycle import atomic_json, now, sha


def configure(session):
    from arsia_pipeline import config, isolated_executor
    root=Path(session.cfg['data_root'])
    for name,module in list(sys.modules.items()):
        if name.startswith('arsia_pipeline') and hasattr(module,'ROOT'):module.ROOT=root
    config.ROOT=root;config.CONFIG=root/'runtime.json'
    os.environ['ARSIA_IMPORT_CONFIG']=str(config.CONFIG)
    isolated_executor.IMAGE=session.cfg['executor_image']


def measurements(session,number,*,maintenance=False):
    root=session.ledger.root
    kinds={'raw':'blobs','legacy_uploads':'uploads','execution_input':'attempts',
           'receipts':'receipts','registry':'registry','recipes':'recipes','source_evidence':'evidence'}
    detail={}
    for key,relative in kinds.items():
        folder=root/relative
        files=[p for p in folder.rglob('*') if p.is_file() and not p.is_symlink()] if folder.exists() else []
        if key=='execution_input':files=[p for p in files if 'input' in p.relative_to(root).parts]
        detail[key]={'logical_bytes':sum(p.stat().st_size for p in files),
                     'allocated_bytes':sum(p.stat().st_blocks*512 for p in files),'files':len(files)}
    for key,selected in [('outputs',[p for p in (root/'attempts').rglob('*') if p.is_file() and 'output' in p.parts]),
                         ('qa_work',[p for p in root.rglob('trusted-qa-*.sqlite') if p.is_file()]),
                         ('qa_json',[p for p in root.rglob('trusted-qa-*.json') if p.is_file()]),
                         ('archives',[p for p in (session.ledger.home/'archives').glob('*.tar.gz')])]:
        detail[key]={'logical_bytes':sum(p.stat().st_size for p in selected),
                     'allocated_bytes':sum(p.stat().st_blocks*512 for p in selected),'files':len(selected)}
    free=shutil.disk_usage(session.ledger.home).free
    return {'upload':number,'after_maintenance':maintenance,'at':now(),'categories':detail,
            'host_available_bytes':free,'docker_volume_bytes':None,
            'limits':'Logical, allocated and Docker bytes are separate; do not sum them as reclaimed space.'}


def documents(recipe, root):
    target=root/'evidence';(target/'sha256').mkdir(parents=True)
    result={}
    for original in recipe['documents']:
        doc=copy.deepcopy(original);receipt=Path(doc['receipt_path'])
        raw=receipt.parent/'sha256'/doc['sha256']
        if sha(raw)!=doc['sha256']:raise AssertionError('Saved source evidence changed')
        shutil.copyfile(raw,target/'sha256'/doc['sha256'])
        for key,suffix in [('receipt_path','.receipt.json'),('text_path','.txt')]:
            if doc.get(key):
                output=target/(doc['document_id']+suffix)
                shutil.copyfile(doc[key],output);output.chmod(0o600);doc[key]=str(output)
        doc['content_path']=str(target/'sha256'/doc['sha256'])
        result[doc['document_id']]=doc
    return result


def workload(output,source,recipe,executor_image,features,deadline,*,imports=10,space=None,filenames=None):
    if filenames is not None and len(filenames)!=imports:
        raise ValueError('Explicit filename sequence must match bounded import count')
    session=TestSession.create(output,suite='same-bytes-ten-upload-v1',
        postgres_image='efedf3595f1d',executor_image=executor_image,storage_features=features,space=space)
    configure(session)
    from arsia_pipeline import agent,api,store,worker
    from arsia_pipeline.adapter_reuse import ADAPTER,controlled
    from arsia_pipeline.codex_runtime import CodexRuntime
    from arsia_pipeline.public_sources import PublicSources
    from fastapi.testclient import TestClient
    def forbidden(*a,**k):raise AssertionError('Storage acceptance forbids model calls or new source downloads')
    agent.gateway=forbidden;CodexRuntime.run=forbidden;PublicSources.fetch_public_source=forbidden
    client=TestClient(api.app)
    reports=[];snapshots=[];start=time.monotonic();success=False
    phases=[]
    def measured(name,fn):
        tick=time.monotonic();at=now()
        try:return fn()
        finally:phases.append({'name':name,'started_at':at,'wall_seconds':time.monotonic()-tick})
    try:
        docs=documents(recipe,session.ledger.root)
        data=source.read_bytes();digest=hashlib.sha256(data).hexdigest()
        if {(r['sha256'],r['size']) for r in recipe['resources']}!={(digest,len(data))}:
            raise AssertionError('Workload needs one exact saved, admitted input fixture')
        first=None;row_digest=None;query_value=None
        for number in range(1,imports+1):
            if time.monotonic()>deadline:raise TimeoutError('Single acceptance batch deadline reached')
            tick=time.monotonic()
            job=client.post('/jobs',json={'label':'Fixed material storage regression '+str(number)});job.raise_for_status()
            jid=job.json()['id'];name=filenames[number-1] if filenames is not None else (source.name if number%2 else 'renamed-identical'+source.suffix)
            response=measured('upload-'+str(number),lambda:client.put('/jobs/'+jid+'/files',params={'filename':name},content=data))
            response.raise_for_status()
            client.post('/jobs/'+jid+'/submit',json={}).raise_for_status()
            if number==1:
                with store.connect() as conn:claimed=worker.claim(conn,session.cfg)
                assert str(claimed['id'])==jid
                work=claimed['work_dir']/'agent';work.mkdir()
                candidate=agent.AgentSession(claimed['files'],work,claimed['options'],lambda *a,**k:None,lambda:None,claimed)
                controlled(candidate,'inspect_bundle',{})
                contract=copy.deepcopy(recipe['contract']);contract.pop('documents',None)
                for resource in contract['resources']:resource['file_id']=candidate.files[0]['id']
                candidate.documents=docs
                controlled(candidate,'set_source_contract',{'contract':contract})
                controlled(candidate,'write_adapter',{'code':ADAPTER,'reason':'Known fixture adapter seeded through fresh sample/full QA and normal registry boundary'})
                for mode in ('sample','full'):
                    run=measured(mode+'-execute',lambda:controlled(candidate,'run_adapter',{'mode':mode}))
                    measured(mode+'-independent-QA',lambda:controlled(candidate,'validate_candidate',{'run_id':run['run_id']}))
                measured('register',lambda:controlled(candidate,'register_adapter',{}))
                controlled(candidate,'publish_candidate',{})
                measured('publish',lambda:worker.publish(claimed,candidate.ready,lambda:None))
            else:measured('worker-'+str(number),lambda:worker.run(once=True))
            result=store.get_job(jid,internal=True)
            expected='succeeded' if number==1 else 'no_change'
            if result['status']!=expected:
                atomic_json(output/('blocked-job-'+str(number)+'.json'),agent.safe(result))
                raise AssertionError('Actual product pathway did not finish as '+expected)
            if first is None:first=result
            assert result['batch_id']==first['batch_id'] and result['release_id']==first['release_id']
            with store.connect() as conn:
                payloads=conn.execute('SELECT payload FROM canonical_crash WHERE batch_id=%s ORDER BY record_id',(result['batch_id'],)).fetchall()
                encoded='\n'.join(json.dumps(r['payload'],sort_keys=True,separators=(',',':')) for r in payloads)
                content_digest=hashlib.sha256(encoded.encode()).hexdigest()
                steps=conn.execute('SELECT name,status,created_at,finished_at FROM agent_steps WHERE session_id=(SELECT id FROM agent_sessions WHERE job_id=%s) ORDER BY id',(jid,)).fetchall()
                usage=conn.execute('SELECT model_calls,tool_calls,compute_seconds FROM agent_sessions WHERE job_id=%s',(jid,)).fetchone()
            assert usage['model_calls']==0
            names=[s['name'] for s in steps if s['status']=='succeeded']
            assert names.count('run_adapter')==2 and names.count('validate_candidate')==2
            assert 'register_adapter' in names and 'publish_candidate' in names
            coverage=result['result']['coverage'];sid=result['source_id']
            q=client.get('/query',params={'source_id':sid,'release_id':str(result['release_id']),
                'from':coverage['from'],'to':coverage['to']});q.raise_for_status()
            value=q.json();value.pop('release_id',None);value.pop('batch_id',None)
            if row_digest is None:row_digest=content_digest;query_value=value
            assert row_digest==content_digest and query_value==value
            report={'number':number,'filename':name,'job_id':jid,'status':result['status'],
                'batch_id':str(result['batch_id']),'release_id':str(result['release_id']),
                'canonical_rows':len(payloads),'canonical_sha256':content_digest,'usage':usage,
                'wall_seconds':time.monotonic()-tick,
                'steps':[{'name':s['name'],'status':s['status'],
                    'seconds':(s['finished_at']-s['created_at']).total_seconds() if s['finished_at'] else None} for s in steps]}
            reports.append(report);atomic_json(output/'uploads.json',reports)
            if number in {1,2,5,10}:
                snapshots.append(measurements(session,number));atomic_json(output/'space.json',snapshots)
            print(output.name,number,expected,round(report['wall_seconds'],2),flush=True)
        source_id=first['source_id']
        with store.connect() as conn:
            state={'jobs':conn.execute('SELECT count(*) AS n FROM jobs').fetchone()['n'],
                'batches':conn.execute('SELECT count(*) AS n FROM batches').fetchone()['n'],
                'releases':conn.execute('SELECT count(*) AS n FROM releases').fetchone()['n'],
                'crashes':conn.execute('SELECT count(*) AS n FROM canonical_crash').fetchone()['n']}
        assert state['jobs']==imports and state['batches']==1 and state['releases']==1
        atomic_json(output/'query.json',query_value)
        if features:
            blobs=[r for r in session.ledger.resources() if r['kind']=='raw_blob']
            receipts=[r for r in session.ledger.resources() if r['kind']=='upload_receipt']
            assert len(blobs)==1 and len(receipts)==imports
            assert not list(session.ledger.root.rglob('trusted-qa-*.sqlite'))
        result={'status':'pass','features':features,'database':state,'row_sha256':row_digest,
            'data_model_calls':0,'data_model_tokens':0,'source_sha256':digest,'source_id':source_id,
            'fixture_mode':'previously validated adapter/contract; fresh QA and registry, no autonomous discovery',
            'wall_seconds':time.monotonic()-start,'phases':phases,'uploads':reports}
        atomic_json(output/'result.json',result);success=True
        return session,result
    finally:
        if not success:
            with store.connect() as conn:
                pending=conn.execute("SELECT id FROM jobs WHERE status NOT IN ('succeeded','no_change','cancelled','failed')").fetchall()
            for item in pending:
                client.post('/jobs/'+str(item['id'])+'/cancel')
        finalized=session.finish(success=success)
        snapshots.append(measurements(session,len(reports),maintenance=True))
        atomic_json(output/'space.json',snapshots);atomic_json(output/'storage-finalize.json',finalized)


def run(args):
    args.output.mkdir(parents=True,mode=0o700,exist_ok=False)
    started=time.monotonic();deadline=started+1800
    atomic_json(args.output/'START.json',{'started_at':now(),'window_seconds':1800,'data_model_call_limit':0})
    recipe=json.loads(args.recipe.read_text());sessions=[];results=[]
    try:
        for label,features in [('disabled',False),('enabled',True)]:
            session,result=workload(args.output/label,args.source,recipe,args.executor_image,features,deadline)
            sessions.append(session);results.append(result)
        assert results[0]['row_sha256']==results[1]['row_sha256']
        assert json.loads((args.output/'disabled/query.json').read_text())==json.loads((args.output/'enabled/query.json').read_text())
        # Two comparable environments stay expanded. The older-session policy
        # is exercised separately by the same shared lifecycle's cold unit test.
        result={'status':'pass','same_current_source_output':True,'runs':results,
            'total_wall_seconds':time.monotonic()-started,'data_model_calls':0,'data_model_tokens':0,
            'limits':['No browser upload or normal website rebinding was performed.',
                      'Safe executor copy fallback remains; no COW savings claimed.']}
        atomic_json(args.output/'result.json',result)
        return 0
    except BaseException as exc:
        atomic_json(args.output/'blocked.json',{'type':type(exc).__name__,'code':getattr(exc,'code',None),
            'message':str(exc)[:1500],'wall_seconds':time.monotonic()-started,
            'stop_condition':'One batch; preserve evidence and do not expand source support.'})
        return 1


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--recipe',required=True,type=Path)
    parser.add_argument('--executor-image',required=True)
    args=parser.parse_args()
    raise SystemExit(run(args))
