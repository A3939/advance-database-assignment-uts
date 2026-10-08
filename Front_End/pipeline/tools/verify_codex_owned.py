"""Explicit single-attempt real Codex experiment in a fresh owned database.

Policy fields are read from an explicit reference runtime. A private Unix-socket
model gateway runs with this experiment; normal 3100 and its gateway are unused.
The reference DB, releases, jobs and configuration are never changed. No contract, adapter,
oracle or answers are supplied to the Agent. All failed evidence is retained.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time
from uuid import uuid4


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value, *, replace=False):
    target = path.with_suffix(path.suffix + '.tmp') if replace else path
    with target.open('w' if replace else 'x') as stream:
        json.dump(value, stream, indent=2, default=str)
    target.chmod(0o600)
    if replace:
        target.replace(path)


def summarize_steps(steps):
    totals = Counter()
    usage = Counter()
    unknown = 0
    for step in steps:
        if step['finished_at']:
            totals[step['name']] += (step['finished_at'] - step['created_at']).total_seconds()
        if step['kind'] != 'model':
            continue
        value = (step.get('result') or {}).get('usage')
        if not isinstance(value, dict):
            unknown += 1
            continue
        for key in ('input_tokens', 'output_tokens', 'total_tokens'):
            if isinstance(value.get(key), int):
                usage[key] += value[key]
        usage['cached_input_tokens'] += (value.get('input_tokens_details') or {}).get('cached_tokens', 0)
        usage['reasoning_output_tokens'] += (value.get('output_tokens_details') or {}).get('reasoning_tokens', 0)
    return {'cumulative_step_seconds': dict(totals), 'known_usage': dict(usage),
            'model_requests': sum(s['kind'] == 'model' for s in steps), 'unknown_usage_requests': unknown,
            'timing_note': 'Step intervals can overlap. Their sum is not wall time.',
            'usage_note': 'Cached input is a subset of input; reasoning output is a subset of output. Missing usage is unknown, not zero.'}


def configure_runtime(cfg, args):
    reference=args.reference_runtime.resolve()
    if not reference.is_file() or reference.is_symlink():raise ValueError('Explicit reference runtime required')
    current=json.loads(reference.read_text())
    if current.get('mode')!='local-test' or current.get('agent_engine','codex')!='codex':
        raise ValueError('This harness requires the current Codex engine')
    cfg['agent_profile']=current.get('agent_profile','expanded-v1')
    from arsia_pipeline.isolated_executor import DEFAULT_LIMITS
    cfg['executor_limits']={**DEFAULT_LIMITS,**(current.get('executor_limits') or {})}
    if 'agent_budget' in current:cfg['agent_budget']=current['agent_budget']
    cfg['agent_gateway_token']=secrets.token_urlsafe(48)
    cfg['autonomous_adaptation_v1']=True
    cfg['bounded_repair_v1']=args.bounded_repair
    cfg['private_model_gateway']={'protocol':'owned-model-gateway-v1','instance_id':cfg['instance_id'],
        'test_session_id':cfg['test_session_id'],'socket_path':str(Path('/tmp').resolve()/('arsia-model-'+cfg['test_session_id'][:12])/'gateway.sock')}
    save(args.output/'reference-policy.json',{'reference_runtime_sha256':digest(reference),
        'agent_profile':cfg['agent_profile'],'executor_limits':cfg['executor_limits'],
        'normal_gateway_used':False,'normal_database_accessed':False})


def run(args):
    from managed_acceptance import child_config
    cfg=child_config(args.output.resolve())
    from arsia_pipeline import config,store,api,worker,agent_policy
    from fastapi.testclient import TestClient
    output=args.output.resolve();source=args.source.resolve()
    protected={str(p):digest(p) for p in (source,args.reference_runtime.resolve(),args.model_env.resolve())}
    started=time.monotonic();observer_stop=threading.Event();observer=None;gateway=None
    log=(output/'private-model-gateway.log').open('xb')
    try:
        store.initialize(cfg)
        project=Path(__file__).resolve().parents[2]
        gateway=subprocess.Popen(['node','--env-file='+str(args.model_env.resolve()),'--import','tsx',
            'scripts/owned-model-gateway.ts',str(config.CONFIG),str(os.getpid())],cwd=project,
            stdout=log,stderr=log,env=dict(os.environ))
        deadline=time.monotonic()+20
        while not (config.ROOT/'model-gateway-ready.json').exists():
            if gateway.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('Private model gateway did not become ready; inspect its preserved log')
            time.sleep(.1)
        ready=json.loads((config.ROOT/'model-gateway-ready.json').read_text())
        assert ready['pid']==gateway.pid and ready['instance_id']==cfg['instance_id']
        if args.probe_only:
            from arsia_pipeline.model_transport import connection
            conn=connection(cfg,5)
            try:
                conn.request('POST','/api/imports/codex-model',body=b'{}',headers={'Content-Type':'application/json'})
                response=conn.getresponse();assert response.status==403;response.read()
            finally:conn.close()
            save(output/'result.json',{'status':'passed','scope':'Cold managed runtime + private socket + real proxy authentication rejection',
                'model_calls':0,'normal_gateway_accessed':False})
            return 0
        with TestClient(api.app) as client:
            response=client.post('/jobs',json={'label':'Fresh isolated research from raw official input; known to developers, empty recipe cache'})
            response.raise_for_status();job_id=response.json()['id']
            with source.open('rb') as stream:
                client.put('/jobs/'+job_id+'/files',params={'filename':args.upload_name or source.name},content=stream.read()).raise_for_status()
            client.post('/jobs/'+job_id+'/submit',json={'answers':args.source_hint} if args.source_hint else {}).raise_for_status()
            save(output/'experiment.json',{'created_at':datetime.now(timezone.utc),'job_id':job_id,
                'source_sha256':digest(source),'source_bytes':source.stat().st_size,'upload_name':args.upload_name or source.name,
                'policy':agent_policy.session_policy(cfg),'explicit_real_model_opt_in':True,
                'oracle_supplied_to_model':False,'contract_or_answers_supplied':False,
                'developer_prior_knowledge':True,'blind_unknown_source_claim':False,
                'fresh_instance':cfg['instance_id'],'website_release_changed':False,
                'upload_entry':'API TestClient','model_gateway':'Owned private Unix socket; same production Codex proxy'})
            def snapshot():
                with store.connect() as conn,conn.transaction():
                    conn.execute('SET TRANSACTION READ ONLY')
                    job=conn.execute('SELECT id,status,stage,message,updated_at FROM jobs WHERE id=%s',(job_id,)).fetchone()
                    sessions=conn.execute('SELECT id,status,model_calls,tool_calls,correction_count FROM agent_sessions WHERE job_id=%s',(job_id,)).fetchall()
                    latest=conn.execute('SELECT s.id,s.kind,s.name,s.status,s.created_at,s.finished_at FROM agent_steps s JOIN agent_sessions a ON a.id=s.session_id WHERE a.job_id=%s ORDER BY s.id DESC LIMIT 6',(job_id,)).fetchall()
                return {'observed_at':datetime.now(timezone.utc),'wall_seconds':time.monotonic()-started,'job':job,'sessions':sessions,'latest_steps':latest}
            def observe():
                previous=None
                while not observer_stop.is_set():
                    try:
                        value=snapshot();save(output/'status.json',value,replace=True)
                        signature=json.dumps([value['job'],value['sessions'],value['latest_steps']],default=str)
                        if signature!=previous:print(json.dumps(value,default=str),flush=True);previous=signature
                    except Exception as exc:print('Owned observer read failed: '+type(exc).__name__,flush=True)
                    observer_stop.wait(5)
            observer=threading.Thread(target=observe,daemon=True);observer.start()
            tick=time.monotonic();worker.run(once=True);worker_seconds=time.monotonic()-tick
            observer_stop.set();observer.join(timeout=10)
            save(output/'status.json',snapshot(),replace=True)
            with store.connect() as conn,conn.transaction():
                conn.execute('SET TRANSACTION READ ONLY')
                job=conn.execute('SELECT * FROM jobs WHERE id=%s',(job_id,)).fetchone()
                steps=conn.execute('SELECT s.* FROM agent_steps s JOIN agent_sessions a ON a.id=s.session_id WHERE a.job_id=%s ORDER BY s.id',(job_id,)).fetchall()
                worker_count=conn.execute('SELECT count(*) AS n FROM worker_state').fetchone()['n']
            save(output/'steps.json',steps);save(output/'job.json',job)
            report={'status':job['status'],'job_id':job_id,'worker_wall_seconds':worker_seconds,
                'worker_rows_after_exit':worker_count,**summarize_steps(steps),'independent_oracle':'not_executed'}
            if job['status'] in {'succeeded','no_change'}:
                from verify_act_isolated import oracle,verify_query
                candidate=output/'published-crashes.jsonl'
                with candidate.open('x') as stream,store.connect() as conn,conn.transaction():
                    conn.execute('SET TRANSACTION READ ONLY')
                    with conn.cursor(name='acceptance_rows') as cur:
                        cur.execute('SELECT payload FROM canonical_crash WHERE batch_id=%s',(job['batch_id'],))
                        for row in cur:stream.write(json.dumps(row['payload'])+'\n')
                independent=oracle(source,candidate)
                response=client.get('/query',params={'source_id':job['source_id'],'release_id':str(job['release_id']),'from':'2015-01-01','to':'2026-12-31'})
                response.raise_for_status();query=response.json()
                save(output/'independent-oracle.json',independent);save(output/'query.json',query)
                report['independent_oracle']=verify_query(query,independent)
                from acceptance_web import verify
                verify(output,job,independent)
            report['wall_seconds']=time.monotonic()-started;save(output/'result.json',report)
            print(json.dumps(report,default=str),flush=True)
            return 0 if job['status'] in {'succeeded','no_change'} else 2
    except BaseException as exc:
        # Do not serialize arbitrary provider/runtime exception values.
        save(output/'failure.json',{'type':type(exc).__name__,'message':'Owned experiment failed; private task evidence retained','wall_seconds':time.monotonic()-started})
        print('Owned experiment failed: '+type(exc).__name__,flush=True)
        return 1
    finally:
        observer_stop.set()
        if observer:observer.join(timeout=10)
        if gateway and gateway.poll() is None:
            gateway.terminate()
            try:gateway.wait(timeout=5)
            except subprocess.TimeoutExpired:gateway.kill();gateway.wait(timeout=5)
        log.close()
        save(output/'protection.json',{'protected_file_hashes_unchanged':{p:digest(Path(p))==h for p,h in protected.items()},
            'private_gateway_stopped':gateway is None or gateway.poll() is not None,
            'normal_database_accessed':False,'normal_gateway_accessed':False,'historical_jobs_resumed':False,
            'limits':'File hashes do not establish normal database contents; TestSession owns database finalization.'})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','output','reference-runtime','model-env'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--executor-image',required=True)
    parser.add_argument('--bounded-repair',action='store_true',help='Enable host-bound diagnostic and in-loop publication for this new experiment only')
    parser.add_argument('--source-hint',default='',help='User objective/evidence URLs; untrusted context, never a mapping or admission')
    parser.add_argument('--upload-name',help='Public filename for a content-addressed source; does not change source bytes')
    parser.add_argument('--storage-policy',required=True,choices=['keep-full'])
    parser.add_argument('--confirm-real-model',action='store_true')
    parser.add_argument('--probe-only',action='store_true',help='Exercise the owned gateway with an unauthenticated request; zero provider calls')
    parser.add_argument('--owned-child',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args()
    upload_name=args.upload_name or args.source.name
    if not args.probe_only and (Path(upload_name).name!=upload_name or '\\' in upload_name or
            Path(upload_name).suffix.lower() not in {'.csv','.xlsx','.xls','.zip','.json','.geojson'}):
        parser.error('A supported upload filename is required; use --upload-name for a content-addressed file')
    if not args.confirm_real_model and not args.probe_only:parser.error('Explicit real model opt-in required; no automatic retries')
    if args.owned_child:raise SystemExit(run(args))
    if args.output.exists():parser.error('Use a new owned output directory')
    if not args.probe_only:
        from arsia_pipeline.codex_sandbox import check_runtime
        check_runtime()
    from managed_acceptance import launch
    raise SystemExit(launch(args,suite='new-raw-research-real-model',configure=lambda cfg:configure_runtime(cfg,args)))
