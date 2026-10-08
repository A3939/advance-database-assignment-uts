import copy
import hashlib
import json
from pathlib import Path

import pytest

from arsia_pipeline.agent_policy import policy, session_policy
from arsia_pipeline.agent_progress import progress_report
from arsia_pipeline.contract_diagnostics import unresolved_diagnostics
from arsia_pipeline.errors import BudgetExhausted, ModelUnavailable, AgentStalled
from arsia_pipeline.task_workspace import create_workspace, read_evidence, read_proposal, admit_proposal
from arsia_pipeline.task_evidence_mcp import handle
from test_contract_patch import offline_session


def event(n, name, status='succeeded', output=None, args=None, attempt='one', contract='c', code='p', mode=None):
    return {'id':n,'name':name,'status':status,'attempt_id':attempt,'arguments':args or {},
        'result':{**(output or {}),'host_context':{'contract_sha256':contract,'code_sha256':code,'run_mode':mode}}}


def diagnostics(steps, **kwargs):
    return unresolved_diagnostics(steps,contract_sha256='c',code_sha256='p',attempt_id='one',**kwargs)


def test_sample_pass_does_not_erase_full_qa_or_full_preflight_failure():
    steps=[event(1,'validate_candidate','failed',{'message':'count mismatch'},mode='full'),
        event(2,'run_adapter','needs_evidence',{'details':{'missing':'coordinate definition'}},args={'mode':'full'}),
        event(3,'validate_candidate',output={'status':'sample_only'},mode='sample')]
    assert {d['category'] for d in diagnostics(steps)}=={'validation.full','execution.full'}
    steps.append(event(4,'validate_candidate',output={'status':'validated'},mode='full'))
    assert diagnostics(steps)==[]


def test_deep_geo_evidence_exact_and_complete_even_when_compact_view_omits_it():
    fact={'document_id':'doc-'+'a'*64,'crs':'EPSG:8059','quote':'An exact official quotation.'}
    nested=fact
    for _ in range(12):nested={'outer':nested}
    steps=[event(1,'run_adapter','needs_evidence',{'details':nested},args={'mode':'full'})]
    assert fact['document_id'] in json.dumps(diagnostics(steps))
    assert fact['quote'] in json.dumps(diagnostics(steps))
    steps[0]['result']['details']['long']='a'*15000
    compact=diagnostics(steps)[0]
    assert compact['diagnostic']['bounded'] and compact['read_full']['arguments']['step_id']==1
    assert fact['quote'] in json.dumps(diagnostics(steps,bounded=False))


def test_edits_mark_revalidation_and_stale_success_cannot_clear_current_failure():
    steps=[event(1,'validate_candidate','failed',{'message':'bad data'},mode='full'),event(2,'patch_adapter')]
    assert diagnostics(steps)[0]['resolution_state']=='needs_revalidation'
    steps.append(event(3,'validate_candidate',output={'status':'validated'},attempt='previous',mode='full'))
    assert len(diagnostics(steps))==1
    steps.append(event(4,'validate_candidate',output={'status':'validated'},contract='old',mode='full'))
    assert len(diagnostics(steps))==1


def test_failed_execution_payload_counts_as_failure_even_if_tool_completed():
    steps=[event(1,'run_adapter',output={'status':'failed','run_id':'run','error':{'type':'NameError'}},args={'mode':'sample'})]
    assert diagnostics(steps)[0]['category']=='execution.sample'
    steps.append(event(2,'run_adapter',output={'status':'succeeded','run_id':'next'},args={'mode':'sample'}))
    assert diagnostics(steps)==[]


def test_successful_proposal_preserves_failed_preflight_until_same_version_rechecked():
    steps = [event(1, 'set_source_contract', output={'status': 'proposed', 'preflight': {'ok': False,
              'blockers': [{'code': 'CRS_UNGROUNDED', 'kind': 'evidence_missing'}]}})]
    assert diagnostics(steps)[0]['category'] == 'preflight'
    assert diagnostics(steps)[0]['resolution_state'] == 'unresolved'
    steps.append(event(2, 'preflight_contract', output={'ok': True}, contract='old'))
    assert len(diagnostics(steps)) == 1
    steps.append(event(3, 'preflight_contract', output={'ok': True}))
    assert diagnostics(steps) == []


def test_policy_pins_model_budget_and_does_not_upgrade_historical_session():
    expanded=session_policy({'agent_profile':'expanded-v1'})
    assert expanded['reasoning_effort']=='high' and expanded['budget']=={'model_calls':120,'tool_calls':200,'correction_count':40,'wall_seconds':7200,'compute_seconds':2400}
    assert session_policy({}, {'agent_policy':expanded})==expanded
    assert session_policy({'agent_profile':'expanded-v1'},{'code':'previous'})['profile']=='baseline-v1'
    stale=copy.deepcopy(expanded);stale['catalog_sha256']='wrong'
    with pytest.raises(ValueError,match='changed'):session_policy({}, {'agent_policy':stale})
    with pytest.raises(ValueError):session_policy({'agent_budget':{'tool_calls':-1}})
    with pytest.raises(ValueError):session_policy({'agent_profile':'model-authored-policy'})


def test_repeated_reads_edits_and_repassing_sample_do_not_manufacture_progress():
    span={'document_id':'doc','quote':'Known fact'}
    steps=[event(1,'read_document',output={'document_id':'doc','citation_spans':[span]}),
        event(2,'validate_candidate',output={'status':'sample_only'})]
    for n in range(3,43):
        steps.append(event(n,'read_document' if n%2 else 'patch_adapter',output={'document_id':'doc','citation_spans':[span]}))
    report=progress_report(steps,policy('expanded-v1')['progress'])
    assert report['state']=='stalled' and report['meaningful_events']==2
    steps.append(event(43,'validate_candidate',output={'status':'sample_only'}))
    assert progress_report(steps,policy('expanded-v1')['progress'])['state']=='stalled'
    steps.append(event(44,'validate_candidate',output={'status':'validated'}))
    assert progress_report(steps,policy('expanded-v1')['progress'])['state']=='continuing'


@pytest.mark.parametrize('error,code',[(BudgetExhausted,'budget_exhausted'),(ModelUnavailable,'model_unavailable'),(AgentStalled,'agent_stalled')])
def test_operational_stops_do_not_ask_user_for_source_data(error,code):
    exc=error('saved progress',{'detail':'test'})
    assert exc.code==code and exc.questions==[]


def workspace(tmp_path, **kwargs):
    root=tmp_path/'task'
    create_workspace(root,contract={'resources':[]},code='def adapt(ctx): pass',diagnostics=[{'quote':'Exact CRS statement'}],
        steps=[{'message':'saved'}],documents={'doc/unsafe':'Exact text'},sdk='SDK',policy=policy('expanded-v1'),identity={'job_id':'fixture'},**kwargs)
    return root


def test_workspace_exact_pagination_no_overwrite_and_no_secrets(tmp_path):
    root=workspace(tmp_path)
    first=read_evidence(root,'evidence/contract.json',0,100)
    assert json.loads(first['text'])=={'resources':[]} and first['next_offset'] is None
    assert not (root/'runtime.json').exists() and not (root/'auth.json').exists()
    assert json.loads((root/'manifest.json').read_text())['execution_ready'] is False
    with pytest.raises(ValueError,match='fresh'):workspace(tmp_path)
    for name in ['../runtime.json','/etc/passwd','proposals/contract.json','evidence/../../runtime.json']:
        with pytest.raises(ValueError):read_evidence(root,name)


def test_workspace_rejects_evidence_tampering_and_proposal_symlinks(tmp_path):
    root=workspace(tmp_path);file=root/'evidence/adapter.py';file.chmod(0o600);file.write_text('tampered')
    with pytest.raises(ValueError,match='changed'):read_evidence(root,'evidence/adapter.py')
    (root/'proposals/contract.json').symlink_to(root/'evidence/contract.json')
    (root/'proposals/adapter.py').write_text('def adapt(ctx):pass')
    with pytest.raises(ValueError,match='symbolic'):read_proposal(root)


def test_proposal_cannot_grant_qa_or_skip_source_contract_validation(tmp_path):
    from arsia_pipeline.registry import digest_json
    session=offline_session(tmp_path);root=workspace(tmp_path)
    (root/'proposals/contract.json').write_text(json.dumps(session.contract))
    (root/'proposals/adapter.py').write_text(session.code+'\n# edit')
    result=admit_proposal(session,root,expected_contract_sha256=digest_json(session.contract),expected_code_sha256=hashlib.sha256(session.code.encode()).hexdigest())
    assert result['status']=='proposed_requires_fresh_sample_and_full_qa'
    assert session.validated is session.registered is session.ready is session.sample_gate is None
    with pytest.raises(ValueError,match='changed'):admit_proposal(session,root,expected_contract_sha256='stale',expected_code_sha256='stale')


def test_mcp_only_lists_and_reads_indexed_evidence(tmp_path):
    root=workspace(tmp_path)
    assert handle(root,{'method':'notifications/initialized'}) is None
    names={t['name'] for t in handle(root,{'id':1,'method':'tools/list'})['result']['tools']}
    assert names=={'list_task_evidence','read_task_evidence'}
    ok=handle(root,{'id':2,'method':'tools/call','params':{'name':'read_task_evidence','arguments':{'name':'evidence/contract.json'}}})
    assert not ok['result']['isError']
    for name,args in [('publish_candidate',{}),('read_task_evidence',{'name':'../runtime.json'}),('read_task_evidence',{'name':'evidence/contract.json','path':'/etc/passwd'})]:
        assert handle(root,{'id':3,'method':'tools/call','params':{'name':name,'arguments':args}})['result']['isError']


def test_partial_qa_improvement_counts_but_same_passing_checks_do_not():
    settings={'warn_after_tools':2,'stop_after_tools':4}
    first=event(1,'validate_candidate','failed',{'qa':[{'code':'Q1','status':'pass'},{'code':'Q2','status':'block'}]},mode='full')
    steps=[first]+[event(n,'patch_adapter') for n in range(2,6)]
    assert progress_report(steps,settings)['state']=='stalled'
    steps.append(event(6,'validate_candidate','failed',{'qa':[{'code':'Q1','status':'pass'},{'code':'Q2','status':'pass'},{'code':'Q3','status':'block'}]},mode='full'))
    assert progress_report(steps,settings)['state']=='continuing'
    for n in range(7,11):steps.append({**steps[-1],'id':n})
    assert progress_report(steps,settings)['state']=='stalled'
