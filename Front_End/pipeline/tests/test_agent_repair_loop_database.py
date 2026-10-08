"""Real durable Session/Bridge loops, scripted tools only; not autonomous admission."""
import copy,json,hashlib
import pytest
from test_backend import isolated_database,client
from test_autonomous_backend import session_for
from test_codex_integration import bridge_for
from test_agent_repair_loop import bound_check
from test_arcgis_representation import bundle
from arsia_pipeline import agent,store,capability_preflight as cp
from arsia_pipeline.errors import NeedsInput,BudgetExhausted,ImportCancelled


@pytest.mark.parametrize('problem',['update','timezone'])
@pytest.mark.parametrize('entry',['codex','legacy'])
def test_durable_existing_loop_revises_and_rechecks(client,tmp_path,monkeypatch,problem,entry):
 s=session_for(client);s.adaptation_v1=True
 contract,files,docs,_=bundle(tmp_path,layer=37,field='seen_on',year=2022)
 good=copy.deepcopy(contract)
 if problem=='update':contract['update']['mode']='partition'
 else:contract['resources'][0]['mapping']['date']['timezone']='America/New_York'
 s.contract=contract
 # Invoke the actual protocol gate within real Session execute_tool; isolate
 # unrelated semantic contract completeness from this repair-loop regression.
 original=s._execute_tool
 def controlled(name,args):
  if name=='preflight_contract':
   c=args.get('contract',s.contract);s.contract=copy.deepcopy(c)
   try:r=bound_check(c,files,docs)
   except NeedsInput as exc:return {'ok':False,'admission':False,'blockers':cp.classified_blockers(exc,operation=name)}
   return {'ok':True,'admission':False,'representation_proofs':r}
  return original(name,args)
 monkeypatch.setattr(s,'_execute_tool',controlled)
 if entry=='codex':
  b=bridge_for(s)
  try:
   out,_=b.tool('preflight_contract',{});first=json.loads((b.workspace/out['result_file']).read_text())
   assert not first['ok'] and first['blockers'][0]['kind']=='adapter_revision' and b.terminal is None
   out,_=b.tool('preflight_contract',{'contract':good});last=json.loads((b.workspace/out['result_file']).read_text())
   assert last['ok'] and not s.ready and not s.validated
   _,error=b.tool('publish_candidate',{});assert error and not s.ready
  finally:b.stop()
 else:
  calls=[]
  def gateway(*a,**kw):
   n=len(calls);calls.append(n)
   if n<2:return {'output':[{'type':'function_call','call_id':str(n),'name':'preflight_contract','arguments':json.dumps({} if n==0 else {'contract':good})}]}
   raise BudgetExhausted('End scripted loop after checking both results')
  monkeypatch.setattr(agent,'gateway',gateway)
  with pytest.raises(BudgetExhausted):s.run()
  outputs=[json.loads(x['output']) for x in s.messages if x.get('type')=='function_call_output']
  assert outputs[0]['ok'] is False and outputs[1]['ok'] is True and not s.ready
 with store.connect() as db:
  steps=db.execute("SELECT result FROM agent_steps WHERE session_id=%s AND name='preflight_contract' ORDER BY id",(s.id,)).fetchall()
 assert len(steps)==2 and not steps[0]['result']['ok'] and steps[1]['result']['ok']
 assert steps[0]['result']['blockers'][0]['details']  # failure retained after repair


@pytest.mark.parametrize('entry',['codex','legacy'])
@pytest.mark.parametrize('failure',['budget','cancel','host','unsupported','receipt'])
def test_terminal_errors_do_not_return_to_model(client,monkeypatch,entry,failure):
 s=session_for(client);s.adaptation_v1=True
 from arsia_pipeline.errors import UnsupportedCapability,ValidationFailure
 exc={'budget':BudgetExhausted('limit'),'cancel':ImportCancelled('stop'),
      'host':RuntimeError('unexpected host failure'),'unsupported':UnsupportedCapability('UNREVIEWED_OPERATOR','No independent verifier'),
      'receipt':ValidationFailure('Receipt bytes corrupt',details={'blockers':[cp.blocker('EVIDENCE_INTEGRITY','environment_dependency','Corrupt receipt')]})}[failure]
 def fail(*a):raise exc
 monkeypatch.setattr(s,'_execute_tool',fail)
 if entry=='codex':
  b=bridge_for(s)
  try:
   b.tool('inspect_bundle',{});assert b.terminal is not None
   with pytest.raises(ValueError):b.tool('get_workflow_state',{})
  finally:b.stop()
 else:
  calls=[]
  def gateway(*a,**kw):
   calls.append(1);assert len(calls)==1,'terminal failure reached another model call'
   return {'output':[{'type':'function_call','call_id':'stop','name':'inspect_bundle','arguments':'{}'}]}
  monkeypatch.setattr(agent,'gateway',gateway)
  with pytest.raises((NeedsInput,ImportCancelled)):s.run()
  assert len(calls)==1
 assert s.ready is None


def test_changed_rejected_contract_and_code_invalidate_old_success(client):
 s=session_for(client);s.adaptation_v1=True;s.contract={'contract_version':'canonical-v2'}
 s.sample_gate=s.validated=s.registered=s.ready={'old':'success'}
 with pytest.raises(ValueError):s.execute_tool('set_source_contract',{'contract':{'contract_version':'bad'}})
 assert all(x is None for x in (s.sample_gate,s.validated,s.registered,s.ready))
 s.code='old';s.sample_gate=s.validated=s.registered=s.ready={'old':'success'}
 s.execute_tool('write_adapter',{'code':'def adapt(ctx): pass','reason':'revision'})
 assert all(x is None for x in (s.sample_gate,s.validated,s.registered,s.ready))
 for tool in ['register_adapter','publish_candidate']:
  with pytest.raises(ValueError):s.execute_tool(tool,{})
