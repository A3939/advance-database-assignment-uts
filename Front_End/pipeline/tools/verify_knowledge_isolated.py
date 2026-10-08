"""Real SA sample/full QA, registry and publication in a NEW PostgreSQL container.

Explicit local acceptance command. No models, live DB connections, existing-job
updates, release selection, or network data downloads. Keeps container/volume,
DB, all attempts and logs; stops only the newly owned container when finished.
"""
import argparse
import copy
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
import zipfile
from uuid import uuid4

PROJECT=Path(__file__).resolve().parents[2]


def save(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,default=str)


def split_crash_years(data):
    """Lossless test transformation, not a claim about publisher packaging."""
    from collections import Counter
    target=io.BytesIO();counts={};proof=[]
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as dest:
        for name in source.namelist():
            raw=source.read(name)
            if not name.endswith('_Crash.csv'):
                dest.writestr(name,raw);continue
            reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''))
            buffers={};writers={};before=Counter();after=Counter()
            for row in reader:
                year=row['Year'];assert year.isdigit() and len(year)==4
                if year not in buffers:
                    buffers[year]=io.StringIO(newline='');writers[year]=csv.DictWriter(buffers[year],fieldnames=reader.fieldnames)
                    writers[year].writeheader();counts[year]=0
                writers[year].writerow(row);counts[year]+=1
                before[hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()]+=1
            for year,buffer in sorted(buffers.items()):
                chunk=buffer.getvalue().encode();member=year+'_Crash.csv';dest.writestr(member,chunk)
                for row in csv.DictReader(io.StringIO(chunk.decode(),newline='')):
                    after[hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()]+=1
                proof.append({'member':member,'sha256':hashlib.sha256(chunk).hexdigest(),'rows':counts[year]})
            assert before==after and sum(before.values())==sum(counts.values())
    return target.getvalue(),{'source_archive_sha256':hashlib.sha256(data).hexdigest(),'partitions':proof,
        'all_field_value_multisets_equal':True,'scope':'Locally derived annual test files; original publisher files unchanged, no official packaging claim.'}


def run(output,research,artifacts,executor_image=None,split_partitions=False,storage_policy=None):
    if storage_policy not in {'recent-two','keep-full'}:
        raise ValueError('Explicit new test storage policy is required')
    output=output.resolve()
    from managed_acceptance import child_config
    cfg=child_config(output)
    from arsia_pipeline import config, isolated_executor
    started=time.monotonic()
    try:
        import psycopg
        from arsia_pipeline import store,api,worker,agent,registry
        from arsia_pipeline.adapter_reuse import ADAPTER,controlled,prepare
        from arsia_pipeline.codex_runtime import CodexRuntime
        from fastapi.testclient import TestClient
        store.initialize(cfg)
        def forbidden(*a,**k):raise AssertionError('Acceptance must make zero model calls')
        agent.gateway=forbidden;CodexRuntime.run=forbidden
        case=json.loads((artifacts/'autonomous-imports/source-downloads/source-cases.json').read_text())['cases']['sa']['upload']
        source=Path(case['path']);data=source.read_bytes();assert hashlib.sha256(data).hexdigest()==case['sha256']
        partition_derivation=None
        if split_partitions:
            data,partition_derivation=split_crash_years(data)
            save(output/'partition-derivation.json',partition_derivation)
            (output/'derived-union-test.zip').write_bytes(data)
        previous=json.loads((artifacts/'autonomous-imports/codex-integration-20261001/sa-2/final-result.json').read_text())['job']['result']['source_contract']
        # Evidence is imported with exact hashes and original receipts. It is
        # checked again by real _proof, with no monkeypatch to any QA gate.
        docs={}
        folder=config.ROOT/'evidence';(folder/'sha256').mkdir(parents=True)
        for key in ('sa','sa-dictionary'):
            fetched=json.loads((research/f'fetch-{key}.json').read_text());doc=copy.deepcopy(fetched['__documents'][0])
            for field,suffix in [('text_path','.txt'),('receipt_path','.receipt.json')]:
                target=folder/(doc['document_id']+suffix);shutil.copyfile(doc[field],target);doc[field]=str(target)
            raw=folder/'sha256'/doc['sha256'];shutil.copyfile(fetched['__files'][0]['path'],raw);doc['content_path']=str(raw)
            docs[doc['document_id']]=doc
        client=TestClient(api.app)
        def new_job(filename):
            response=client.post('/jobs',json={'label':'Isolated source knowledge acceptance'});response.raise_for_status();ident=response.json()['id']
            client.put('/jobs/'+ident+'/files',params={'filename':filename},content=data).raise_for_status()
            client.post('/jobs/'+ident+'/submit',json={}).raise_for_status()
            with store.connect() as conn:job=worker.claim(conn,cfg)
            assert str(job['id'])==ident
            return job
        first=new_job('sa-initial.zip')
        first_agent=first['work_dir']/'agent';first_agent.mkdir()
        session=agent.AgentSession(first['files'],first_agent,first['options'],lambda *a,**k:None,lambda:None,first)
        controlled(session,'inspect_bundle',{})
        from managed_acceptance import copy_public_reference
        session.intake.register_files([copy_public_reference(case,config.ROOT/'resource-receipts')])
        session.files=list(session.intake.files)
        contract=copy.deepcopy(previous);contract.pop('documents',None)
        for r in contract['resources']:
            fragment={'crash':'_Crash.csv','unit':'_Units.csv','casualty':'_Casualty.csv'}[r['role']]
            candidates=sorted((f for f in session.files if f['name'].endswith(fragment)),key=lambda f:f['name'])
            r['file_id']=candidates[0]['id']
            if split_partitions and r['role']=='crash':
                r['partitions']=[{'file_id':f['id'],'table':copy.deepcopy(r.get('table',{}))} for f in candidates]
        session.documents=docs
        controlled(session,'set_source_contract',{'contract':contract})
        controlled(session,'write_adapter',{'code':ADAPTER,'reason':'Deterministic replay acceptance from historical contract and current identical evidence bytes'})
        for mode in ('sample','full'):
            print('initial',mode,flush=True)
            executed=controlled(session,'run_adapter',{'mode':mode})
            controlled(session,'validate_candidate',{'run_id':executed['run_id']})
        from acceptance_oracles import sa as sa_oracle
        independent=sa_oracle(data, Path(session.validated['canonical_path']).parent)
        save(output/'independent-oracle.json',independent)
        controlled(session,'register_adapter',{});controlled(session,'publish_candidate',{})
        worker.publish(first,session.ready,lambda:None)
        first_result=store.get_job(first['id'])
        save(output/'initial.json',agent.safe(first_result))
        # Independent source oracle: csv/Decimal, no canonical.project or SDK.
        counts={};fatal=0;deaths=0;casualties=0
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                if not name.endswith('.csv'):continue
                with archive.open(name) as raw:
                    rows=csv.DictReader(io.TextIOWrapper(raw,encoding='utf-8-sig'));n=0
                    for row in rows:
                        n+=1
                        if name.endswith('_Crash.csv'):
                            deaths+=int(row['Total Fats']);casualties+=int(row['Total Cas']);fatal+=int(int(row['Total Fats'])>0)
                    counts[name]=n
        expected={'crash_count':sum(v for k,v in counts.items() if k.endswith('_Crash.csv')),
                  'fatal_crash_count':fatal,'fatalities':deaths,'casualties':casualties,
                  'canonical_unit_count':sum(v for k,v in counts.items() if k.endswith('_Units.csv')),
                  'canonical_casualty_count':sum(v for k,v in counts.items() if k.endswith('_Casualty.csv'))}
        assert all(first_result['result']['summary'][k]==v for k,v in expected.items())
        from acceptance_web import verify as verify_web
        verify_web(output,first_result,independent)
        second=new_job('completely-renamed.zip')
        print('automatic replay',flush=True)
        second_agent=second['work_dir']/'agent';second_agent.mkdir()
        ready=agent.agent_process(second['files'],second_agent,second['options'],lambda *a,**k:None,lambda:None,job=second)
        assert ready is not None
        worker.publish(second,ready,lambda:None)
        second_result=store.get_job(second['id']);save(output/'replay.json',agent.safe(second_result))
        assert all(second_result['result']['summary'][k]==v for k,v in expected.items())
        assert second_result['status']=='no_change'
        assert first_result['release_id']==second_result['release_id']
        # A recognized file is no excuse for a bad candidate. Deliberately
        # emit a fabricated count using the real no-network executor, then
        # require independent QA and both downstream gates to reject it.
        from arsia_pipeline.errors import ValidationFailure
        third=new_job('negative-qa.zip');third_agent=third['work_dir']/'agent';third_agent.mkdir()
        bad=agent.AgentSession(third['files'],third_agent,third['options'],lambda *a,**k:None,lambda:None,third)
        controlled(bad,'inspect_bundle',{})
        from arsia_pipeline.adapter_reuse import ReuseCache
        cached,decision=ReuseCache(cfg['knowledge_root'],cfg['instance_id']).match(bad.files)
        assert cached and decision['route']=='verified_recipe_requires_fresh_QA'
        bad.documents={d['document_id']:d for d in cached['documents']}
        bad.intake.register_files(cached.get('binding_files',[]))
        bad.files=list(bad.intake.files)
        controlled(bad,'set_source_contract',{'contract':cached['contract']})
        malicious=ADAPTER.replace("ctx.emit(resource['grain'], ctx.project(role, locator, row))", "projected = ctx.project(role, locator, row)\n            if resource['grain'] == 'crash': projected['fatalities'] = 999\n            ctx.emit(resource['grain'], projected)")
        controlled(bad,'write_adapter',{'code':malicious,'reason':'Negative acceptance fixture: fabricated count must fail'})
        executed=controlled(bad,'run_adapter',{'mode':'sample'})
        try:controlled(bad,'validate_candidate',{'run_id':executed['run_id']})
        except ValidationFailure as exc:negative={'qa_rejected':True,'message':str(exc)}
        else:raise AssertionError('QA accepted fabricated counts')
        for tool in ('register_adapter','publish_candidate'):
            try:controlled(bad,tool,{})
            except ValueError:negative[tool+'_rejected']=True
            else:raise AssertionError('Failed QA reached '+tool)
        # Exercise the actual Codex MCP bridge against this isolated session.
        from arsia_pipeline.codex_bridge import TaskBridge
        workspace=output/'bridge-task';(workspace/'evidence').mkdir(parents=True)
        bridge=TaskBridge(bad,workspace)
        try:
            answer,error=bridge.tool('read_source_knowledge',{'dataset_id':'act-road-crash'})
            assert not error and 'act-road-crash' in json.dumps(answer)
            answer,error=bridge.tool('read_source_evidence',{'evidence_id':'sa-dictionary','locator':'page:2'})
            assert not error and '8059' in json.dumps(answer)
            answer,error=bridge.tool('compare_source_metadata',{'baseline_evidence_id':'sa',
                'document_id':next(key for key in docs if key.endswith('9eda764877c0dd5fbf8745440d8cbaefc243871611ac943092346c199641dc59')),'provider':'ckan'})
            assert not error and 'unchanged_semantics' in json.dumps(answer)
        finally:bridge.stop()
        with store.connect() as conn:
            current=conn.execute('SELECT release_id FROM current_release').fetchone()['release_id']
        assert str(current)==str(first_result['release_id'])
        negative['release_unchanged']=True
        store.update_job(third['id'],'failed','Intentional negative QA test; evidence retained')
        with store.connect() as conn:
            usage=conn.execute('SELECT model_calls,tool_calls FROM agent_sessions ORDER BY created_at').fetchall()
            steps=conn.execute('SELECT name,status FROM agent_steps ORDER BY id').fetchall()
        assert all(u['model_calls']==0 for u in usage)
        report={'status':'passed','input_sha256':hashlib.sha256(data).hexdigest(),'independent_expected':expected,'full_row_oracle':independent,
            'model_calls':0,'usage':usage,'steps':steps,'same_release':True,'replay_status':second_result['status'],
            'elapsed_seconds':time.monotonic()-started,'mode':'no-model deterministic replay, not autonomous discovery',
            'negative_QA':negative,'codex_bridge_tools_verified':True,
            'limits':['Full row oracle checks raw values, keys, dates, categories, counts, links and inverse projection; geodetic epoch accuracy is not certified.',
                      'This SA experiment does not execute or admit ACT.']}
        if partition_derivation:
            report['partition_derivation']=partition_derivation
            union=first_result['result']['admission']['evidence']['parser_plans']['crash']['union_plan']
            assert len(union['inputs'])==len(partition_derivation['partitions'])
            report['union_plan']=union
        save(output/'acceptance.json',report);print(json.dumps({k:report[k] for k in ['status','model_calls','replay_status','elapsed_seconds']}),flush=True)
    except BaseException as exc:
        save(output/'failure.json',{'type':type(exc).__name__,'message':str(exc),'elapsed_seconds':time.monotonic()-started})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--storage-policy',required=True,choices=['recent-two','keep-full']);p.add_argument('--output',required=True,type=Path);p.add_argument('--research',required=True,type=Path)
    p.add_argument('--executor-image',help='Reviewed local executor image for this acceptance process only')
    p.add_argument('--split-crash-partitions',action='store_true',help='Derive lossless annual crash partitions for explicit union acceptance')
    p.add_argument('--artifacts',required=True,type=Path,help='Read-only existing source receipts and historical contracts')
    p.add_argument('--owned-child',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args()
    if not a.owned_child:
        if a.output.exists():p.error('Use a fresh isolated output directory')
        from managed_acceptance import launch
        raise SystemExit(launch(a,suite='SA-knowledge-offline-acceptance'))
    run(a.output,a.research.resolve(),a.artifacts.resolve(),a.executor_image,a.split_crash_partitions,a.storage_policy)
