"""Opt-in Codex acceptance; keeps every created DB, config, job and receipt.

No tests use the website's current release DB. --prepare-only creates a fresh
marked database and a real uploaded job. Run it via the real worker separately.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'pipeline'))
from arsia_pipeline import store, api, worker, agent
from arsia_pipeline.config import ROOT, read_config


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as handle:json.dump(value,handle,indent=2,default=str)


def state(cfg):
    with store.connect(cfg) as conn,conn.transaction():
        conn.execute('SET TRANSACTION READ ONLY')
        return {'jobs':conn.execute('SELECT id,status,attempt FROM jobs ORDER BY id').fetchall(),
                'release':conn.execute('SELECT * FROM current_release').fetchall(),
                'counts':{table:conn.execute('SELECT count(*) AS n FROM '+table).fetchone()['n'] for table in ['batches','canonical_crash','canonical_unit','releases']}}


def prepare(directory,case):
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from fastapi.testclient import TestClient
    original=read_config();before=state(original)
    name='arsia_imports_test_codex_'+uuid4().hex[:12]
    parts=conninfo_to_dict(original['dsn']);parts['dbname']=name
    cfg={**original,'database':name,'dsn':make_conninfo(**parts),'instance_id':uuid4().hex,
         'agent_engine':'codex','agent_profile':'expanded-v1','socket_path':'/tmp/'+name+'.sock'}
    cfg.pop('agent_budget',None)
    config=ROOT/(name+'.json')
    with store.connect(original) as conn:conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    save(config,cfg);os.environ['ARSIA_IMPORT_CONFIG']=str(config);store.initialize(cfg)
    with TestClient(api.app) as client:
        job=client.post('/jobs',json={'label':'Codex '+case+' isolated acceptance','source_hint':'South Australia road crash data 2020-2024' if case=='sa' else 'Protocol smoke test only'}).json()
        if case=='sa':
            item=json.loads((PROJECT/'artifacts/autonomous-imports/source-downloads/source-cases.json').read_text())['cases']['sa']['upload']
            data=Path(item['path']).read_bytes();assert hashlib.sha256(data).hexdigest()==item['sha256'];filename=item['name']
        else:data=b'id,year\na,2024\n';filename='protocol.csv'
        response=client.put('/jobs/'+job['id']+'/files',params={'filename':filename},content=data);response.raise_for_status()
        response=client.post('/jobs/'+job['id']+'/submit',json={});response.raise_for_status()
    receipt={'created_at':datetime.now(timezone.utc),'database':name,'config_path':str(config),'job_id':job['id'],
             'retained':True,'baseline_before':before,'baseline_after_prepare':state(original),'case':case}
    assert receipt['baseline_before']==receipt['baseline_after_prepare']
    save(directory/'experiment.json',receipt)
    print(json.dumps({k:receipt[k] for k in ['database','config_path','job_id','case']}),flush=True)
    return cfg,receipt


def main():
    p=argparse.ArgumentParser();p.add_argument('--case',choices=['smoke','sa'],required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--confirm-real-model',action='store_true')
    p.add_argument('--prepare-only',action='store_true');args=p.parse_args()
    if not args.confirm_real_model: p.error('Explicit --confirm-real-model required')
    if args.output.exists():p.error('Use a fresh output directory')
    args.output.mkdir(parents=True,mode=0o700)
    cfg,receipt=prepare(args.output,args.case)
    if args.prepare_only:return
    if args.case=='sa':worker.run(once=True)
    else:
        from arsia_pipeline.codex_runtime import CodexRuntime
        from arsia_pipeline.errors import NeedsInput
        with store.connect() as conn:job=worker.claim(conn,cfg)
        session=agent.AgentSession(job['files'],job['work_dir'],job['options'],lambda *a,**k:None,lambda:None,job)
        try:
            CodexRuntime(session).run(prompt='This is a transport acceptance test, not an actual dataset import. Read evidence/files.json with the shell, call get_workflow_state, then call request_missing_information with message "Codex protocol smoke completed" and questions ["This is test evidence only"]. Do not investigate official sources or execute an adapter.')
        except NeedsInput as exc:
            passed=str(exc)=='Codex protocol smoke completed'
            store.update_job(job['id'],'needs_input',str(exc),error={'code':exc.code,'message':str(exc)})
            with store.connect() as conn:
                conn.execute("UPDATE attempts SET status='needs_input',finished_at=now() WHERE id=%s",(job['attempt_id'],))
            receipt['smoke_passed']=passed;receipt['error']={'type':type(exc).__name__,'message':str(exc),'details':exc.details}
        except BaseException as exc:
            receipt['smoke_passed']=False;receipt['error']={'type':type(exc).__name__,'message':str(exc)}
        receipt['session_id']=str(session.id);receipt['runtime_state']=session.runtime_state
    with store.connect() as conn:
        receipt['job']=conn.execute('SELECT id,status,error,result FROM jobs WHERE id=%s',(receipt['job_id'],)).fetchone()
        receipt['steps']=conn.execute('SELECT kind,name,status,result FROM agent_steps WHERE session_id IN (SELECT id FROM agent_sessions WHERE job_id=%s) ORDER BY id',(receipt['job_id'],)).fetchall()
    save(args.output/'result.json',agent.safe(receipt))
    print(json.dumps({'smoke_passed':receipt.get('smoke_passed'),'job':str(receipt['job']['status']),'error':receipt.get('error')}),flush=True)


if __name__=='__main__':main()
