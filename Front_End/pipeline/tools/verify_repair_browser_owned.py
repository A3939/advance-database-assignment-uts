"""One new owned source release for a bounded live browser window. No historical restart."""
import argparse,json,os,sys,threading,time
from pathlib import Path
from uuid import uuid4
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'pipeline/tools'))
from managed_acceptance import launch,child_config
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--executor-image',required=True);p.add_argument('--storage-policy',required=True);p.add_argument('--owned-child',action='store_true');args=p.parse_args();args.dataset='tas'
if not args.owned_child:
 def configure(cfg):cfg.update(knowledge_root=str(Path(cfg['data_root'])/'recipes'),autonomous_adaptation_v1=True,bounded_repair_v1=True)
 raise SystemExit(launch(args,suite='live-browser-synthetic-limited-release',configure=configure))
cfg=child_config(args.output)
# Fresh instance only; use the existing real-QA synthetic capability test.
os.environ['ARSIA_REGRESSION_INSTANCE']=cfg['instance_id']
sys.path.insert(0,str(root/'pipeline/tests'))
import pytest
from fastapi.testclient import TestClient
from arsia_pipeline import store,api
with store.connect() as db:
 assert db.execute('SELECT count(*) AS n FROM jobs').fetchone()['n']==0
from test_limited_publication import test_limited_nonspatial_source_publishes_and_remains_limited_everywhere
with pytest.MonkeyPatch.context() as patch:
 from arsia_pipeline import agent as initial_agent
 patch.setattr(initial_agent,'read_config',lambda:{**cfg,'bounded_repair_v1':False})
 with TestClient(api.app) as client:
  test_limited_nonspatial_source_publishes_and_remains_limited_everywhere(client,patch)
with store.connect() as db:
 jobs=db.execute('SELECT id,status,batch_id,release_id,source_id FROM jobs').fetchall()
assert len(jobs)==1 and jobs[0]['status']=='succeeded'
initial={k:str(v) for k,v in jobs[0].items()}
(args.output/'initial.json').write_text(json.dumps(initial,indent=2)+'\n')
(args.output/'synthetic-acceptance.json').write_text(json.dumps({'status':'passed','synthetic':True,'official_input':False,'model_calls':0,'sample_full_real_QA':True,'source_id':initial['source_id'],'release_id':initial['release_id'],'rows':1,'geography':'unsupported','target_satisfied':False},indent=2)+'\n')

# New lifecycle fixtures use the actual worker's terminal handling. They are
# labelled as synthetic UI cases and never invoke a model or resume old jobs.
from arsia_pipeline import worker, agent, repair_context
from arsia_pipeline.errors import NeedsInput, UnsupportedCapability, ValidationFailure, ImportCancelled
with TestClient(api.app) as client:
 for status in ['needs_input','failed','cancelled']:
  created=client.post('/jobs',json={'label':'Browser fixture: '+status}).json()
  client.put('/jobs/'+created['id']+'/files',params={'filename':'fixture.csv'},content=b'ID,Year,Severity\n1,2024,Injury\n').raise_for_status()
  client.post('/jobs/'+created['id']+'/submit',json={}).raise_for_status()
  with store.connect() as db:job=worker.claim(db,cfg)
  assert str(job['id'])==created['id']
  def fixture_agent(files,work,options,progress,cancel,**kwargs):
   session=agent.AgentSession(files,work,{'answers':'Synthetic browser fixture: retain the original goal and explicit limits.'},progress,cancel,job)
   exc=(UnsupportedCapability('FIXTURE_READER_GAP','Synthetic fixture: independent validation for this source transformation is missing.')
        if status=='needs_input' else ValidationFailure('Synthetic fixture: full candidate reconciliation failed.')
        if status=='failed' else ImportCancelled('Synthetic fixture cancellation'))
   repair_context.record(session,exc,'validate_candidate')
   session.runtime_state['diagnostic_runs']=[{'binding':{'purpose':'value_comparison'},'status':'failed'}]
   session.persist()
   raise exc
  def require_agent(*args,**kwargs):raise NeedsInput('Synthetic browser investigation')
  with pytest.MonkeyPatch.context() as patch:
   from arsia_pipeline import processing
   patch.setattr(processing,'process_bundle',require_agent)
   patch.setattr(agent,'agent_process',fixture_agent)
   worker.execute(job,threading.Event())
  assert store.get_job(created['id'])['status']==status
with store.connect() as db:
 browser_jobs=db.execute('SELECT id,label,status FROM jobs ORDER BY created_at').fetchall()
(args.output/'browser-fixtures.json').write_text(json.dumps(browser_jobs,default=str,indent=2)+'\n')

from arsia_pipeline.api import app
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
import uvicorn
scope=FastAPI();token=uuid4().hex
@scope.middleware('http')
async def isolate(request:Request,next_handler):
 # Browser exercises live product reads and local Studio writes only. Reject
 # import writes at this disposable API, so no model or new import can start.
 if request.method!='GET':return JSONResponse({'error':'Read-only browser publication instance'},status_code=403)
 return await next_handler(request)
@scope.get('/__acceptance_identity')
def identity():return {'instance_id':cfg['instance_id'],'test_session_id':cfg['test_session_id'],'marker':token}
scope.mount('/',app)
folder=Path('/tmp')/('arsia-imports-'+cfg['test_session_id'][:12]);folder.mkdir(mode=0o700)
socket=str(folder/'api.sock')
server=uvicorn.Server(uvicorn.Config(scope,uds=socket,log_level='error',lifespan='off'))
thread=threading.Thread(target=server.run,daemon=True);thread.start()
try:
 for _ in range(100):
  if server.started:break
  if not thread.is_alive():raise RuntimeError('Owned API did not start')
  time.sleep(.1)
 else:raise RuntimeError('Owned API startup timeout')
 os.chmod(socket,0o600)
 initial=json.loads((args.output/'initial.json').read_text())
 manifest={'instance_id':cfg['instance_id'],'test_session_id':cfg['test_session_id'],'marker':token,'socket_path':socket,'release_id':initial['release_id'],'batch_id':initial['batch_id'],'source_id':initial['source_id'],'child_pid':os.getpid(),'normal_database_writes':False,'import_writes_allowed':False}
 (args.output/'browser-ready.json').write_text(json.dumps(manifest,indent=2)+'\n');print('BROWSER_READY',flush=True)
 deadline=time.monotonic()+1800
 while time.monotonic()<deadline:
  control=args.output/'browser-finish.json'
  if control.is_file():
   done=json.loads(control.read_text());assert done['marker']==token
   break
  time.sleep(.5)
 else:raise RuntimeError('Browser acceptance window ended without completion')
finally:
 server.should_exit=True;thread.join(timeout=10)
 if thread.is_alive():raise RuntimeError('Owned API failed to stop')
