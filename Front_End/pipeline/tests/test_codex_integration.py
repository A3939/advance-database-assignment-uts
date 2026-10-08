import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from test_autonomous_backend import isolated_database, client, session_for
from arsia_pipeline import agent, codex_sandbox, store
from arsia_pipeline.codex_bridge import TaskBridge
from arsia_pipeline.errors import BudgetExhausted


def bridge_for(session):
    root=session.work_dir/'bridge-test'; (root/'evidence').mkdir(parents=True); (root/'proposals').mkdir()
    return TaskBridge(session,root)


def test_os_boundary_denies_host_reads_writes_and_other_ports(tmp_path):
    if platform.system()!='Darwin': pytest.skip('macOS launcher')
    root=tmp_path/'allowed'; home=root/'home'; task=root/'task'
    for path in [home,task/'scratch',task/'proposals',task/'evidence']: path.mkdir(parents=True,exist_ok=True)
    secret=tmp_path/'host-secret'; secret.write_text('sentinel')
    (task/'evidence/proof').write_text('immutable evidence')
    (task/'scratch/host-link').symlink_to(secret)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
        def log_message(self,*_): pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    profile=tmp_path/'boundary.sb'; profile.write_text(codex_sandbox.profile(task,home,server.server_port))
    # Direct probes exercise descendants of the outer boundary, without a model.
    code='''import json, pathlib, socket, urllib.request
result={}
for name,path in [('host_read',%r),('project_read',%r),('volume_alias_read',%r),('symlink_read',%r)]:
 try: pathlib.Path(path).read_bytes(); result[name]=False
 except PermissionError: result[name]=True
for name,path in [('host_write',%r),('evidence_write',%r)]:
 try: pathlib.Path(path).write_text('changed'); result[name]=False
 except PermissionError: result[name]=True
pathlib.Path(%r).write_text('allowed');result['task_write']=True
try: socket.create_connection(('127.0.0.1',3100),timeout=1);result['other_port']=False
except PermissionError: result['other_port']=True
result['bridge']=urllib.request.urlopen('http://127.0.0.1:%s',timeout=2).read()==b'ok'
print(json.dumps(result))
''' % (str(secret),str(codex_sandbox.PROJECT/'README.md'),'/System/Volumes/Data'+str(secret),str(task/'scratch/host-link'),str(secret),str(task/'evidence/proof'),str(task/'scratch/probe'),server.server_port)
    try:
        result=subprocess.run(['/usr/bin/sandbox-exec','-f',str(profile),str(codex_sandbox.PYTHON),'-c',code],
            cwd=task,env=codex_sandbox.environment(task,home,'task-only','task-only'),capture_output=True,text=True,timeout=20)
        assert result.returncode==0,result.stderr
        assert all(json.loads(result.stdout).values()),result.stdout
        assert secret.read_text()=='sentinel'
        assert (task/'evidence/proof').read_text()=='immutable evidence'
    finally: server.shutdown();server.server_close();thread.join()


def test_scoped_mcp_auth_schema_and_exact_evidence(client):
    session=session_for(client);bridge=bridge_for(session)
    try:
        conn=http.client.HTTPConnection('127.0.0.1',bridge.port)
        conn.request('POST','/mcp',body=b'{}',headers={'Authorization':'Bearer wrong'})
        response=conn.getresponse();assert response.status==403;response.read();conn.close()
        with pytest.raises(ValueError):bridge.tool('arbitrary_shell',{})
        with pytest.raises(ValueError):bridge.tool('read_task_state',{'kind':'contract','path':'/etc/passwd'})
        result,error=bridge.tool('get_workflow_state',{})
        assert not error and session.usage['tool_calls']==1
        assert (bridge.workspace/result['result_file']).is_file()
        with store.connect() as conn:
            saved=conn.execute('SELECT result FROM agent_steps WHERE id=%s',(result['step_id'],)).fetchone()
        assert saved['result']['host_context']['attempt_id']==str(session.job['attempt_id'])
    finally:bridge.stop()


def test_codex_tools_share_durable_budget_and_block_early_publication(client):
    session=session_for(client);bridge=bridge_for(session)
    try:
        result,error=bridge.tool('publish_candidate',{})
        assert error and not session.ready and 'Full QA' in result['output']['message']
        session.usage['tool_calls']=session.budget['tool_calls']
        with pytest.raises(BudgetExhausted):bridge.tool('get_workflow_state',{})
    finally:bridge.stop()


def test_actual_bridge_compact_result_and_targeted_retrieval(client,monkeypatch):
    session=session_for(client);bridge=bridge_for(session)
    original=session.execute_tool
    value={'file_id':'fixture','complete':True,'row_count':765,
           'columns':[{'name':f'field_{i}','frequencies':list(range(100))} for i in range(200)]}
    def execute(name,args):
        return value if name=='profile_dataset' else original(name,args)
    monkeypatch.setattr(session,'execute_tool',execute)
    try:
        result,error=bridge.tool('profile_dataset',{'file_id':'fixture'})
        assert not error and result['projection']['returned_output_bytes']<=6144
        assert result['output']['compact'] and result['projection']['full_result_bytes']>48000
        raw=(bridge.workspace/result['result_file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==result['projection']['result_file_sha256']
        assert json.loads(raw)==value
        args={**result['projection']['retrieval']['arguments'],'pointer':'/columns/199/name'}
        exact,error=bridge.tool('read_task_state',args)
        assert not error and json.loads(exact['output']['text'])=='field_199'
        index=json.loads((bridge.workspace/'evidence/index.json').read_text())
        ref=next(r for r in index['results'] if r['step_id']==result['step_id'])
        assert ref['content_hash']==exact['output']['content_hash']
        assert (bridge.workspace/'evidence/issues.json').is_file()
        assert (bridge.workspace/'evidence/facts.json').stat().st_size<30000
        assert session.usage['model_calls']==0 and session.usage['tool_calls']==2
    finally:bridge.stop()


def test_actual_codex_progress_stops_new_hash_loop_before_model_transport(client,monkeypatch):
    from arsia_pipeline.config import read_config
    from arsia_pipeline.errors import AgentStalled
    from arsia_pipeline.issue_progress import VERSION
    cfg={**read_config(),'agent_engine':'codex','agent_profile':'expanded-v1'}
    monkeypatch.setattr(agent,'read_config',lambda:cfg)
    session=session_for(client);bridge=bridge_for(session)
    def execute(name,args):
        if name=='preflight_contract':
            return {'ok':False,'blockers':[{'code':'CRS_UNGROUNDED','role':'crash','field':'X','kind':'evidence_missing'}]}
        if name=='fetch_public_source':
            return {'status':'fetched','url':args['url'],'sha256':hashlib.sha256(args['url'].encode()).hexdigest()}
        raise AssertionError('Unexpected controlled operation')
    monkeypatch.setattr(session,'execute_tool',execute)
    try:
        bridge.tool('preflight_contract',{})
        for i in range(39):bridge.tool('fetch_public_source',{'url':f'https://data.example.gov.au/new-document/{i}'})
        progress=session.progress_state()
        assert progress['version']==VERSION and progress['state']=='stalled'
        assert progress['meaningful_events']==0 and len(progress['unresolved_issues'])==1
        assert session.budget['model_calls']==120 and session.budget['tool_calls']==200
        with pytest.raises(AgentStalled) as failure:
            bridge.relay(None,{'model':'gpt-6.1-sol','stream':True})
        assert failure.value.questions==[] and failure.value.details['unresolved_issues'][0]['identity']['code']=='CRS_UNGROUNDED'
        assert session.usage['model_calls']==0 and session.usage['tool_calls']==40
        saved=json.loads((bridge.workspace/'evidence/issues.json').read_text())
        assert saved['progress']['state']=='stalled'
        from arsia_pipeline.agent_status import status as public_status
        summary=public_status(session.job)['investigation']
        assert summary['state']=='stalled' and summary['unresolved_count']==1
        assert 'CRS_UNGROUNDED' not in json.dumps(summary) and 'dataset_url' not in summary
        restored=agent.AgentSession(session.files,session.work_dir,{},lambda *a,**k:None,lambda:None,session.job)
        assert restored.progress_version==VERSION and restored.progress_state()==progress
        with pytest.raises(AgentStalled):restored.check_budget(new_model=True)
    finally:bridge.stop()


def test_progress_rule_does_not_migrate_historical_paused_checkpoint(client,monkeypatch):
    from arsia_pipeline.config import read_config
    cfg={**read_config(),'agent_engine':'codex','agent_profile':'expanded-v1'}
    monkeypatch.setattr(agent,'read_config',lambda:cfg)
    session=session_for(client)
    session.persist('needs_input')
    # Test-owned session simulates a checkpoint made before this version existed.
    with store.connect() as conn:
        conn.execute("UPDATE agent_sessions SET checkpoint=checkpoint-'progress_version' WHERE id=%s",(session.id,))
    restored=agent.AgentSession(session.files,session.work_dir,{},lambda *a,**k:None,lambda:None,session.job)
    assert restored.engine=='codex' and restored.progress_version=='legacy'


@pytest.mark.parametrize('tool_name', ['set_source_contract','preflight_contract'])
def test_host_records_failed_proposal_scope_without_changing_contract(client,monkeypatch,tool_name):
    from arsia_pipeline.config import read_config
    from arsia_pipeline.errors import NeedsInput
    cfg={**read_config(),'agent_engine':'codex','agent_profile':'expanded-v1'}
    monkeypatch.setattr(agent,'read_config',lambda:cfg)
    session=session_for(client);bridge=bridge_for(session)
    proposal={'source':{'source_id':'pending_source','dataset_url':'https://data.example.gov.au/dataset'},
              'resources':[{'role':'crash','grain':'crash','key':['ID']}]}
    def fail(*a,**k):raise NeedsInput('Missing specific CRS',[],{'blockers':[{'code':'CRS_UNGROUNDED','role':'crash'}]})
    monkeypatch.setattr(session,'execute_tool',fail)
    try:
        bridge.tool(tool_name,{'contract':proposal})
        issue=session.progress_state()['unresolved_issues'][0]
        assert issue['identity']['source']['source_id']=='pending_source' and not session.contract
        assert issue['identity']['resource']=={'grain':'crash','key':['ID']}
    finally:bridge.stop()


def test_nested_patch_failure_records_candidate_scope_not_saved_contract(client,monkeypatch):
    from arsia_pipeline.config import read_config
    from arsia_pipeline.registry import digest_json
    cfg={**read_config(),'agent_engine':'codex','agent_profile':'expanded-v1'}
    monkeypatch.setattr(agent,'read_config',lambda:cfg)
    session=session_for(client);bridge=bridge_for(session)
    saved={'source':{'source_id':'original_source'},'resources':[{'role':'crash','grain':'crash','key':['ID']}]}
    session.contract=saved
    try:
        # Missing contract_version intentionally fails before any mutation.
        bridge.tool('patch_source_contract',{'expected_contract_sha256':digest_json(saved),
            'patches':[{'op':'replace','path':'/source/source_id','value':'other_source'}],
            'reason':'Test attempted identity retained in failed proposal diagnostic'})
        issue=session.progress_state()['unresolved_issues'][0]
        assert issue['identity']['source']['source_id']=='other_source'
        assert session.contract==saved
    finally:bridge.stop()


def test_engine_and_runtime_pinned_across_resume(client,monkeypatch):
    from arsia_pipeline.config import read_config
    cfg={**read_config(),'agent_engine':'codex','agent_profile':'expanded-v1'}
    monkeypatch.setattr(agent,'read_config',lambda:cfg)
    session=session_for(client)
    session.runtime_state={'thread_id':'c38ac08f-ec8a-4715-aa7e-91a104c1f829'};session.persist()
    cfg['agent_engine']='legacy'
    restored=agent.AgentSession(session.files,session.work_dir,{},lambda *a,**k:None,lambda:None,session.job)
    assert restored.engine=='codex' and restored.runtime_state==session.runtime_state
    assert restored.validated is None and restored.sample_gate is None


def test_cancelled_task_refuses_model_and_tools_before_inference(client):
    from arsia_pipeline.errors import ImportCancelled
    session=session_for(client);bridge=bridge_for(session)
    session._cancel=lambda:(_ for _ in ()).throw(ImportCancelled())
    try:
        with pytest.raises(ImportCancelled):bridge.tool('get_workflow_state',{})
        with pytest.raises(ImportCancelled):bridge.relay(None,{'model':'gpt-6.1-sol','stream':True})
        assert session.usage['model_calls']==0 and session.usage['tool_calls']==0
    finally:bridge.stop()


def test_supervisor_reaps_its_group_when_parent_dies(tmp_path):
    import signal
    import sys
    import time
    from arsia_pipeline import codex_supervisor
    # A disposable parent owns this supervisor and a sleeping descendant. No
    # existing worker or user process is interrupted by this lifecycle test.
    receipt=tmp_path/'child.pid'
    code='import os,time,pathlib;pathlib.Path('+repr(str(receipt))+').write_text(str(os.getpid()));time.sleep(60)'
    parent_code='''import os,subprocess,sys,time
subprocess.Popen([sys.executable,%r,'--parent',str(os.getpid()),sys.executable,'-c',%r])
time.sleep(60)
''' % (str(Path(codex_supervisor.__file__)),code)
    parent=subprocess.Popen([sys.executable,'-c',parent_code])
    try:
        deadline=time.monotonic()+5
        while not receipt.exists() and time.monotonic()<deadline:time.sleep(.05)
        assert receipt.exists()
        child=int(receipt.read_text())
        parent.kill();parent.wait(timeout=2)
        while time.monotonic()<deadline:
            try:os.kill(child,0)
            except ProcessLookupError:break
            time.sleep(.05)
        else:pytest.fail('Scoped descendant outlived its parent')
    finally:
        if parent.poll() is None:parent.kill();parent.wait()


def test_completed_response_releases_slot_before_client_can_continue(client,monkeypatch):
    from arsia_pipeline import codex_bridge
    from arsia_pipeline.config import read_config
    cfg={**read_config(),'agent_gateway_token':'synthetic-test-only'}
    monkeypatch.setattr(codex_bridge,'read_config',lambda:cfg)
    session=session_for(client);bridge=bridge_for(session)
    seen=[]
    class Response:
        status=200
        def __init__(self):self.sent=False
        def read1(self,*_):
            if self.sent:return b''
            self.sent=True
            return b'data: {"type":"response.completed","response":{"id":"test","status":"completed","model":"gpt-6.1-sol","usage":{"total_tokens":9}}}\n\n'
    class Connection:
        sock=None
        def __init__(self,*a,**k):pass
        def request(self,*a,**k):assert k['headers']['X-Arsia-Task']==cfg['instance_id']+':'+str(session.id)
        def getresponse(self):return Response()
        def close(self):pass
    class Writer:
        def write(self,value):
            # Codex may observe completion and call again at this exact point.
            seen.append(bridge.model_active)
            with store.connect() as conn:
                row=conn.execute("SELECT status,result FROM agent_steps WHERE session_id=%s AND kind='model'",(session.id,)).fetchone()
            assert row['status']=='succeeded' and row['result']['usage']['total_tokens']==9
        def flush(self):pass
    class Handler:
        wfile=Writer()
        def send_response(self,*_):pass
        def send_header(self,*_):pass
        def end_headers(self):pass
    monkeypatch.setattr(codex_bridge.http.client,'HTTPConnection',Connection)
    try:
        bridge.relay(Handler(),{'model':'gpt-6.1-sol','stream':True})
        assert seen==[False]
        assert session.usage['model_calls']==1
    finally:bridge.stop()


def test_intake_tools_allow_omitted_optional_required_schema(client):
    session=session_for(client);bridge=bridge_for(session)
    try:
        result,error=bridge.tool('inspect_bundle',{})
        assert not error and result['output'].get('status')!='error'
        assert session.usage['tool_calls']==1
    finally:bridge.stop()


@pytest.mark.parametrize('usage',[None,{'input_tokens':100,'output_tokens':20,'total_tokens':120}])
def test_compaction_preserves_usage_and_consumes_model_budget(client,monkeypatch,usage):
    from arsia_pipeline import codex_bridge
    from arsia_pipeline.config import read_config
    cfg={**read_config(),'agent_gateway_token':'synthetic-test-only'}
    monkeypatch.setattr(codex_bridge,'read_config',lambda:cfg)
    session=session_for(client);bridge=bridge_for(session)
    payload=json.dumps({'object':'response.compaction','id':'compact-test','usage':usage,'output':[]}).encode()
    class Response:
        status=200
        def read(self,*_):return payload
    class Connection:
        def __init__(self,*a,**k):pass
        def request(self,*a,**kwargs):assert kwargs['headers']['X-Arsia-Operation']=='compact'
        def getresponse(self):return Response()
        def close(self):pass
    class Writer:
        def write(self,value):
            assert value==payload and bridge.model_active is False
        def flush(self):pass
    class Handler:
        path='/v1/responses/compact'
        wfile=Writer()
        def send_response(self,*_):pass
        def send_header(self,*_):pass
        def end_headers(self):pass
    monkeypatch.setattr(codex_bridge.http.client,'HTTPConnection',Connection)
    try:
        bridge.relay(Handler(),{'model':'gpt-6.1-sol','input':[]})
        with store.connect() as conn:
            row=conn.execute("SELECT name,status,result FROM agent_steps WHERE session_id=%s AND kind='model'",(session.id,)).fetchone()
        assert row['name']=='codex.compact' and row['status']=='succeeded'
        assert row['result']['usage']==usage and row['result']['usage_known']==bool(usage)
        assert session.usage['model_calls']==1
    finally:bridge.stop()


def test_runtime_tree_is_outside_strict_adapter_storage_and_home_is_stable(client):
    from arsia_pipeline.codex_runtime import CodexRuntime
    from uuid import uuid4
    session=session_for(client)
    first=CodexRuntime(session)
    assert not first.root.is_relative_to(Path(session.job['work_dir']).parent)
    session.job={**session.job,'attempt_id':uuid4(),'work_dir':Path(session.job['work_dir']).parent/str(uuid4())}
    second=CodexRuntime(session)
    assert first.home==second.home and first.root!=second.root
