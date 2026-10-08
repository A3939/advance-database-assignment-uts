"""Opt-in cancellation probe, restricted to a retained Codex TEST database."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arsia_pipeline import store,api
from arsia_pipeline.config import read_config
from fastapi.testclient import TestClient


def snapshot(job):
    with store.connect() as c:
        return {'job':c.execute('SELECT id,status,attempt,release_id FROM jobs WHERE id=%s',(job,)).fetchone(),
            'session':c.execute("SELECT id,model_calls,tool_calls,correction_count,checkpoint->'runtime_state' AS runtime FROM agent_sessions WHERE job_id=%s",(job,)).fetchone(),
            'current_release':c.execute('SELECT * FROM current_release').fetchall(),
            'running_steps':c.execute("SELECT count(*) AS n FROM agent_steps WHERE session_id IN (SELECT id FROM agent_sessions WHERE job_id=%s) AND status='running'",(job,)).fetchone()['n'],
            'worker':c.execute('SELECT active_job_id FROM worker_state').fetchall()}


def main():
    p=argparse.ArgumentParser();p.add_argument('--job-id',type=UUID,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--confirm-cancel-test',action='store_true');args=p.parse_args();cfg=read_config()
    if not args.confirm_cancel_test or not cfg['database'].startswith('arsia_imports_test_codex_'):p.error('Explicit Codex TEST cancellation required')
    report={'started_at':datetime.now(timezone.utc).isoformat(),'database':cfg['database'],'triggered':False}
    deadline=time.monotonic()+900
    while time.monotonic()<deadline:
        before=snapshot(args.job_id)
        if before['job']['status'] in store.FINAL:
            report['not_triggered_reason']='Job reached terminal state before the sample gate';break
        with store.connect() as c:
            ready=c.execute("SELECT id FROM agent_steps WHERE session_id=%s AND name='validate_candidate' AND status='succeeded' AND result->>'status'='sample_only' ORDER BY id DESC LIMIT 1",(before['session']['id'],)).fetchone() if before['session'] else None
        if ready:
            report['before']=before;report['sample_step_id']=ready['id']
            with TestClient(api.app) as client:
                response=client.post('/jobs/'+str(args.job_id)+'/cancel');response.raise_for_status()
            report['triggered']=True;print('Cancellation requested after actual sample QA',flush=True)
            end=time.monotonic()+45
            while time.monotonic()<end:
                after=snapshot(args.job_id)
                if after['job']['status']=='cancelled' and not after['worker']:break
                time.sleep(.2)
            report['after']=after
            report['passed']=after['job']['status']=='cancelled' and after['current_release']==before['current_release'] and not after['worker'] and after['running_steps']==0
            break
        time.sleep(.3)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,default=str));args.output.chmod(0o600)
    print(json.dumps({'triggered':report['triggered'],'passed':report.get('passed')}),flush=True)


if __name__=='__main__':main()
