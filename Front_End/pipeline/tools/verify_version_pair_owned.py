"""Explicit real-Agent SA version-pair acceptance in one newly owned instance.

Original archives are uploaded unchanged. No contracts, mappings, adapters or
expected output rows are supplied to the Agent. Archived retrieval receipts are
context only; trusted tools must obtain/recheck binding evidence independently.
"""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import zipfile

from verify_codex_owned import configure_runtime, digest, save, summarize_steps


def inventory(path):
    result={}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.lower().endswith('.csv'):continue
            with archive.open(name) as raw:
                rows=csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8-sig'))
                keys=set(); count=0; counts={}; years={}
                for row in rows:
                    count+=1; key=row.get('REPORT_ID'); keys.add(key)
                    year=(row.get('Year') or (key or '')[:4]);years[year]=years.get(year,0)+1
                    for field in ('Total Fats','Total Cas'):
                        if field in row:counts[field]=counts.get(field,0)+int(row[field])
                result[name]={'rows':count,'unique_crash_keys':len(keys),'years':years,'counts':counts}
    return result


def run(args):
    from managed_acceptance import child_config
    cfg=child_config(args.output.resolve())
    from arsia_pipeline import config, store, api, worker, query, agent_policy
    from fastapi.testclient import TestClient
    output=args.output.resolve(); protected={str(p):digest(p) for p in [args.old.resolve(),args.current.resolve(),args.reference_runtime.resolve(),args.model_env.resolve()]}
    tick=time.monotonic(); gateway=None; log=(output/'private-model-gateway.log').open('xb'); reports=[]
    receipt=json.loads(args.old_receipt.read_text())
    assert digest(args.old)==receipt['sha256'] and args.old.stat().st_size==receipt['bytes']
    old_url=receipt['requested_url']
    current_receipt=json.loads(args.current_receipt.read_text())
    assert digest(args.current)==current_receipt['sha256'] and args.current.stat().st_size==current_receipt['size']
    current_url=current_receipt['requested_url']
    hint=('Investigate these real South Australian road crash publication versions. Establish whether stable cross-version crash keys exist using complete comparisons and publisher evidence; do not assume date suffix removal proves correspondence. '
          'Preserve independently verified versions if record correspondence or replacement authority cannot be proved, and state that limitation. If independent versions are appropriate, select their proposed namespace before sample/full execution to avoid invalidating and duplicating a full run. Selection does not grant admission. '
          'Every version must independently pass source binding and full QA. Compare all crash, unit and casualty tables; keep unverified mapping explicit. '
          'Archived research evidence (not admission): historical retrieval '+str(receipt['fetched_at'])+', SHA256 '+receipt['sha256']+', URL '+old_url+'. Current archive URL '+current_url+'. '
          'The original archives are being tested in successive new jobs in the same isolated registry. Fetch comparison references through controlled tools; do not execute uploaded programs.')
    try:
        store.initialize(cfg)
        gateway=subprocess.Popen(['node','--env-file='+str(args.model_env.resolve()),'--import','tsx','scripts/owned-model-gateway.ts',str(config.CONFIG),str(os.getpid())],
            cwd=Path(__file__).resolve().parents[2],stdout=log,stderr=log,env=dict(os.environ))
        end=time.monotonic()+20
        while not (config.ROOT/'model-gateway-ready.json').exists():
            if gateway.poll() is not None or time.monotonic()>end:raise RuntimeError('Owned gateway unavailable')
            time.sleep(.1)
        save(output/'input-inventory.json',{'old':inventory(args.old),'current':inventory(args.current),
            'original_hashes':protected,'hints_are_untrusted':True,'contract_or_mapping_supplied':False,
            'policy':agent_policy.session_policy(cfg)})
        with TestClient(api.app) as client:
            published={}
            for label,path,filename in [('old',args.old,'2020_data_sa_as_at_20210527.zip'),
                ('current',args.current,'2020-2024_data_sa_crash_as_at_20250919.zip'),
                ('replay-old',args.old,'renamed-old.zip'),('replay-current',args.current,'renamed-current.zip')]:
                dest=output/label;dest.mkdir();start=time.monotonic()
                before=query.catalog()
                job_id=client.post('/jobs',json={'label':'SA official version pair — '+label}).json()['id']
                with path.open('rb') as raw:
                    client.put('/jobs/'+job_id+'/files',params={'filename':filename},content=raw.read()).raise_for_status()
                context = hint+' This job is '+label+'.'
                if label == 'current' and reports and reports[0]['status']=='succeeded':
                    context += (' The preceding real Agent job '+reports[0]['job_id']+
                        ' already investigated both exact archives, executed full cross-version comparisons, and published only the verified old independent version. '
                        'Reuse that existing investigation and registry evidence where applicable; do not repeat its comparison script merely because this is a new input job. '
                        'This job must still independently bind the current original archive, choose its own candidate, run fresh sample/full QA and publish transactionally. '
                        'Prior comparison is not source admission or record-mapping authority. Inspect the existing registry through the available tools.')
                client.post('/jobs/'+job_id+'/submit',json={'answers':context}).raise_for_status()
                stopped=threading.Event()
                def observe():
                    while not stopped.is_set():
                        try:
                            j=store.get_job(job_id)
                            public={'job_id':job_id,'status':j['status'],'stage':j['stage'],'message':j['message'],'seconds':time.monotonic()-start}
                            save(dest/'status.json',public,replace=True);print(json.dumps(public),flush=True)
                        except Exception:pass
                        stopped.wait(15)
                observer=threading.Thread(target=observe,daemon=True);observer.start()
                try:worker.run(once=True)
                finally:stopped.set();observer.join(3)
                job=store.get_job(job_id)
                with store.connect() as conn,conn.transaction():
                    conn.execute('SET TRANSACTION READ ONLY')
                    steps=conn.execute('SELECT s.* FROM agent_steps s JOIN agent_sessions a ON a.id=s.session_id WHERE a.job_id=%s ORDER BY s.id',(job_id,)).fetchall()
                    attempts=conn.execute('SELECT status,finished_at,error FROM attempts WHERE job_id=%s',(job_id,)).fetchall()
                save(dest/'job.json',job);save(dest/'steps.json',steps);save(dest/'attempts.json',attempts)
                report={'label':label,'job_id':job_id,'status':job['status'],'wall_seconds':time.monotonic()-start,**summarize_steps(steps)}
                after=query.catalog();save(dest/'catalog.json',after)
                if job['status'] not in {'succeeded','no_change'}:
                    assert after==before
                    report['previous_release_preserved']=True;report['remaining']='Subsequent pair/replay checks not run after this failed new attempt.'
                    reports.append(report);break
                result=job['result']; independent=result.get('version_scope')
                report['independent_version']=independent
                if not independent:
                    report['remaining']='Published source did not choose independent-version isolation; cross-version safety is not established by this run.'
                    reports.append(report);break
                q=query.query(job['source_id'],after['release_id'],'2020-01-01','2024-12-31');save(dest/'query.json',q)
                original=inventory(path); crash=next(v for k,v in original.items() if 'crash' in k.lower())
                assert q['summary']['crash_count']==crash['rows']
                assert q['summary']['fatalities']==crash['counts']['Total Fats']
                assert q['summary']['casualties']==crash['counts']['Total Cas']
                assert result['database_verification']['orphan_count']==0
                for grain,word in [('unit','units'),('casualty','casualty')]:
                    expected=next(v['rows'] for k,v in original.items() if word in k.lower())
                    assert result['database_verification']['canonical_'+grain+'_count']==expected
                if label.startswith('replay'):
                    assert job['status']=='no_change' and after==before
                    assert report['model_requests']==0
                    report['idempotent_without_model']=True
                else:published[label]=job['source_id']
                reports.append(report);save(dest/'result.json',report)
            complete=len(reports)==4 and all(r.get('independent_version') for r in reports)
            if complete:
                assert len(set(published.values()))==2
                assert set(published.values())=={s['source_id'] for s in query.catalog()['sources']}
            report={'status':'passed' if complete else 'incomplete','runs':reports,'wall_seconds':time.monotonic()-tick,
                'cross_version_record_correspondence':'not established by version isolation',
                'limitations':'Failure mutation is covered separately by explicit database fixtures; this harness never fabricates source admission.'}
            save(output/'result.json',report);print(json.dumps(report),flush=True)
            return 0 if complete else 2
    finally:
        if gateway and gateway.poll() is None:
            gateway.terminate()
            try:gateway.wait(5)
            except subprocess.TimeoutExpired:gateway.kill();gateway.wait(5)
        log.close();save(output/'protection.json',{'hashes_unchanged':{p:digest(Path(p))==h for p,h in protected.items()},'normal_runtime_used':False})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('old','current','old-receipt','current-receipt','output','reference-runtime','model-env'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--executor-image',required=True)
    parser.add_argument('--storage-policy',choices=['keep-full'],required=True)
    parser.add_argument('--confirm-real-model',action='store_true')
    parser.add_argument('--owned-child',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();args.bounded_repair=True
    if not args.confirm_real_model:parser.error('Explicit real model opt-in required')
    if args.owned_child:raise SystemExit(run(args))
    if args.output.exists():parser.error('Use a new output directory')
    from managed_acceptance import launch
    raise SystemExit(launch(args,suite='sa-version-pair-real-agent',configure=lambda cfg:configure_runtime(cfg,args)))
