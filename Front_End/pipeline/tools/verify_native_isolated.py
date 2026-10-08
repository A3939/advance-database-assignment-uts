"""Actual frozen QLD input through the existing native worker and publication.

Independent CSV oracle; no model or native revision claims. The A -> admitted B
-> old A policy transition is separately covered by explicit DB test doubles.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import time


def save(path,value):
    with path.open('x') as stream:json.dump(value,stream,indent=2,default=str)
    path.chmod(0o600)


def oracle(path):
    expected={};raw=0
    months={name:i for i,name in enumerate('January February March April May June July August September October November December'.split(),1)}
    severity={'Fatal':'FATAL','Hospitalisation':'HOSPITALISATION','Medical treatment':'MEDICAL_TREATMENT','Minor injury':'MINOR_INJURY','Property damage only':'PROPERTY_DAMAGE_ONLY'}
    with path.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            raw+=1;year=int(row['Crash_Year'])
            if not 2020<=year<=2024:continue
            key=row['Crash_Ref_Number'];assert key not in expected
            counts=[int(row['Count_Casualty_'+suffix]) if row['Count_Casualty_'+suffix] else None for suffix in ('Fatality','Hospitalised','MedicallyTreated','MinorInjury')]
            expected[key]={'year':year,'month':months[row['Crash_Month']] if row['Crash_Month'] else None,
                'severity':severity[row['Crash_Severity']] if row['Crash_Severity'] else '__MISSING__',
                'fatalities':counts[0],'casualties':sum(counts) if all(c is not None for c in counts) else None}
    return raw,expected


def run(args):
    from managed_acceptance import child_config
    cfg=child_config(args.output.resolve())
    from arsia_pipeline import store,api,worker,agent
    from arsia_pipeline.codex_runtime import CodexRuntime
    from fastapi.testclient import TestClient
    started=time.monotonic();source=args.source.resolve();output=args.output.resolve()
    with source.open('rb') as stream:before=hashlib.file_digest(stream,'sha256').hexdigest()
    assert before=='975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704'
    raw,expected=oracle(source);store.initialize(cfg)
    def forbidden(*a,**kw):raise AssertionError('Native acceptance must not invoke a model')
    agent.gateway=forbidden;CodexRuntime.run=forbidden
    with TestClient(api.app) as client:
        results=[]
        for filename in ('qld_crash_locations.csv','renamed-frozen-qld.csv'):
            response=client.post('/jobs',json={'label':'Actual pinned QLD native acceptance'});response.raise_for_status();ident=response.json()['id']
            with source.open('rb') as stream:client.put('/jobs/'+ident+'/files',params={'filename':filename},content=stream.read()).raise_for_status()
            client.post('/jobs/'+ident+'/submit',json={}).raise_for_status()
            tick=time.monotonic();worker.run(once=True);job=store.get_job(ident)
            save(output/('initial.json' if not results else 'replay.json'),job)
            assert job['status']==('succeeded' if not results else 'no_change'),job.get('error')
            assert job['result']['publication_gate']['admission_level']=='fixed_native'
            with store.connect() as conn,conn.transaction():
                conn.execute('SET TRANSACTION READ ONLY');seen=set()
                with conn.cursor(name='native_oracle') as cursor:
                    cursor.execute('SELECT record_id,payload FROM canonical_crash WHERE batch_id=%s',(job['batch_id'],))
                    for row in cursor:
                        key=row['record_id'];assert key not in seen;seen.add(key)
                        assert {name:row['payload'][name] for name in expected[key]}==expected[key]
                assert seen==expected.keys()
                assert conn.execute('SELECT count(*) AS n FROM agent_sessions').fetchone()['n']==0
            assert job['result']['summary']['raw_record_count']==raw
            response=client.get('/query',params={'source_id':job['source_id'],'release_id':job['release_id'],'from':'2020-01-01','to':'2024-12-31'});response.raise_for_status()
            query=response.json();assert query['summary']['crash_count']==len(expected)
            assert query['summary']['fatalities']==sum(r['fatalities'] or 0 for r in expected.values())
            if results:assert job['release_id']==results[0]['release_id'] and job['batch_id']==results[0]['batch_id']
            results.append({'job_id':ident,'status':job['status'],'release_id':job['release_id'],'batch_id':job['batch_id'],'worker_seconds':time.monotonic()-tick})
    with source.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==before
    save(output/'result.json',{'status':'passed','model_calls':0,'raw_rows':raw,'canonical_rows':len(expected),'input_sha256':before,
        'results':results,'independent_all_key_date_category_count_oracle':True,'wall_seconds':time.monotonic()-started,
        'limits':['Native reviewed 2020–2024 scope only; no map capability.','Not a real cross-version or browser acceptance.']})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--executor-image',required=True);parser.add_argument('--storage-policy',choices=['keep-full'],required=True)
    parser.add_argument('--owned-child',action='store_true',help=argparse.SUPPRESS);args=parser.parse_args()
    if args.owned_child:run(args)
    else:
        if args.output.exists():parser.error('Fresh output required')
        from managed_acceptance import launch
        raise SystemExit(launch(args,suite='frozen-native-qld-acceptance'))
