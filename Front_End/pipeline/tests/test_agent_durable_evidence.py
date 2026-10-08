import json

import pytest

from test_autonomous_backend import isolated_database, client, session_for
from arsia_pipeline import agent, store
from arsia_pipeline.errors import ModelUnavailable


def test_full_diagnostic_and_contract_readable_after_compaction_and_resume(client):
    session=session_for(client)
    session.contract={'source':{'source_id':'test_source'},'definitions':{'late_field':'keep exact '+('definition '*15000)}}
    session.code='def adapt(ctx): pass'
    quote='Site coordinates use EPSG:8059 and datum GDA2020.'
    deep={'document_id':'doc-'+'a'*64,'quote':quote,'crs':'EPSG:8059'}
    for _ in range(12):deep={'official_evidence':deep}
    step=session.step('tool','run_adapter',{'mode':'full'})
    session.active_tool={'name':'run_adapter','arguments':{'mode':'full'}}
    session.finish_step(step,{'message':'Coordinate proof required','details':deep},'needs_evidence')
    for n in range(25):
        read=session.step('tool','read_document',{'search':str(n)})
        session.finish_step(read,{'document_id':f'doc-{n}','citation_spans':[]})
    session.messages=[{'role':'user','content':'Earlier context '*1000} for _ in range(110)]
    session.persist('needs_input')
    restored=agent.AgentSession(session.files,session.work_dir,{},lambda *a,**k:None,lambda:None,session.job)
    wire=restored.wire_messages()
    assert len(wire)<100 and str(step) in json.dumps(wire)
    assert quote in restored.execute_tool('read_task_state',{'kind':'diagnostics','max_chars':32000})['text']
    full=restored.execute_tool('read_task_state',{'kind':'tool_result','step_id':step})
    assert quote in full['text'] and 'doc-'+'a'*64 in full['text']
    chunks=[];offset=0;hashes=set()
    while True:
        part=restored.execute_tool('read_task_state',{'kind':'contract','offset':offset,'max_chars':32000})
        chunks.append(part['text']);hashes.add(part['sha256'])
        if part['next_offset'] is None:break
        offset=part['next_offset']
    assert len(hashes)==1 and json.loads(''.join(chunks))==session.contract


def test_task_state_cannot_read_other_sessions_or_model_steps(client):
    one=session_for(client);step=one.step('tool','inspect_bundle',{});one.finish_step(step,{'private':'different task'})
    two=session_for(client)
    with pytest.raises(ValueError,match='belong'):two.execute_tool('read_task_state',{'kind':'tool_result','step_id':step})
    model=two.step('model','responses',{});two.finish_step(model,{'provider':'metadata'})
    with pytest.raises(ValueError,match='belong'):two.execute_tool('read_task_state',{'kind':'tool_result','step_id':model})


def test_targeted_durable_result_retrieval_after_resume(client):
    from arsia_pipeline.agent_facts import sha
    session=session_for(client)
    step=session.step('tool','read_document',{})
    quote='Exact official quote — '+('all source values '*1000)
    session.finish_step(step,{'details':{'x/y':[{'quote':quote}]},'unused':'large '*10000})
    session.persist()
    restored=agent.AgentSession(session.files,session.work_dir,{},lambda *a,**k:None,lambda:None,session.job)
    chunks=[];offset=0;hashes=set()
    while True:
        result=restored.execute_tool('read_task_state',{'kind':'tool_result','step_id':step,
            'pointer':'/details/x~1y/0/quote','offset':offset,'max_chars':3000})
        chunks.append(result['text']);hashes.add(result['content_hash'])
        if result['next_offset'] is None:break
        offset=result['next_offset']
    assert json.loads(''.join(chunks))==quote and len(hashes)==1
    with store.connect() as conn:
        saved=conn.execute('SELECT result FROM agent_steps WHERE id=%s',(step,)).fetchone()['result']
    assert hashes=={sha(saved)}
    with pytest.raises(ValueError,match='existing'):
        restored.execute_tool('read_task_state',{'kind':'tool_result','step_id':step,'pointer':'/does-not-exist'})


def test_permanent_model_error_pauses_after_one_call_without_fallback(client,monkeypatch):
    session=session_for(client);calls=[]
    def unavailable(*args):
        calls.append(args[3]['model'])
        raise agent.GatewayFailure(503,{'provider_status':404,'code':'model_not_found'})
    monkeypatch.setattr(agent,'gateway',unavailable)
    monkeypatch.setattr(session,'transport_backoff',lambda *a:pytest.fail('Permanent errors must not retry'))
    with pytest.raises(ModelUnavailable):session.run()
    assert calls==['gpt-6-luna'] and session.usage['model_calls']==1


def test_expanded_session_sends_sol_high_and_pins_settings(client,monkeypatch):
    from arsia_pipeline.config import read_config
    from test_autonomous_backend import tool_call
    cfg={**read_config(),'agent_profile':'expanded-v1'}
    monkeypatch.setattr(agent,'read_config',lambda:cfg)
    session=session_for(client);seen=[]
    def response(*args):
        seen.append(args[3])
        return tool_call('request_missing_information',{'message':'Fixture needs official evidence','questions':['Fixture evidence?']},1)
    monkeypatch.setattr(agent,'gateway',response)
    from arsia_pipeline.errors import NeedsInput
    with pytest.raises(NeedsInput):session.run()
    assert seen[0]['model']=='gpt-6.1-sol' and seen[0]['reasoning_effort']=='high'
    assert session.budget['model_calls']==120 and session.budget['tool_calls']==200
    restored=agent.AgentSession(session.files,session.work_dir,{},lambda *a,**k:None,lambda:None,session.job)
    assert restored.agent_policy==session.agent_policy and restored.usage['model_calls']==1
