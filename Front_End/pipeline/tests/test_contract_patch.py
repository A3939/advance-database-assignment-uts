import copy
import hashlib
import json
import time
from types import SimpleNamespace

import pytest

from arsia_pipeline import agent, registry
from arsia_pipeline.contract_patch import patch_contract
from arsia_pipeline.errors import NeedsInput, ValidationFailure


def proposal():
    return {"contract_version":"canonical-v2", "source":{"source_id":"demo_source", "publisher":"Official fixture",
        "title":"Events", "dataset_url":"https://data.example.gov.au/events", "licence":"CC BY", "jurisdiction":["AU"],
        "coverage":{"from":"2024-01-01","to":"2024-12-31"}}, "update":{"mode":"snapshot"},
        "resources":[{"role":"events","file_id":"input","grain":"crash","key":["ID"],"table":{"format":"csv"},
            "mapping":{"date":{"field":"DATE","formats":["%Y-%m-%d"],"precision":"day"}}}],
        "relations":[], "definitions":{}, "evidence":{"date":[{"document_id":"doc-"+"a"*64,"quote":"The DATE field records the event date."}]}}


def patch(c, operations, **opts):
    return patch_contract(c, opts.get('expected',registry.digest_json(c)), operations, opts.get('reason','Correct the declared mapping'))


def test_small_patch_preserves_exact_existing_evidence_and_original():
    c=proposal(); original=copy.deepcopy(c)
    updated=patch(c,[{"op":"add","path":"/resources/0/mapping/fatalities","value":{"field":"DEATHS"}}])
    assert c==original and updated['evidence']==original['evidence']
    assert updated['resources'][0]['mapping']['fatalities']=={'field':'DEATHS'}
    assert updated['resources'][0]['mapping']['date']==c['resources'][0]['mapping']['date']


def test_array_edits_and_escaped_object_keys_follow_pointer_rules():
    c=proposal(); c['definitions']={'a/b~c':1}
    updated=patch(c,[{'op':'replace','path':'/definitions/a~1b~0c','value':2},
        {'op':'add','path':'/relations/-','value':{'child':'p','parent':'events'}},
        {'op':'remove','path':'/definitions/a~1b~0c'}])
    assert updated['definitions']=={} and len(updated['relations'])==1
    assert c['definitions']=={'a/b~c':1} and c['relations']==[]


@pytest.mark.parametrize('operation',[
    {'op':'add','path':'/documents','value':[]}, {'op':'add','path':'/native_context','value':{}},
    {'op':'add','path':'/definitions/confirmed','value':True}, {'op':'add','path':'/executor_limits','value':{}},
    {'op':'replace','path':'','value':{}}, {'op':'add','path':'/resources/00','value':{}},
    {'op':'add','path':'/resources/-1','value':{}}, {'op':'replace','path':'/resources/-','value':{}},
    {'op':'replace','path':'/resources/99','value':{}}, {'op':'remove','path':'/definitions/absent'},
    {'op':'add','path':'/definitions/~bad','value':1}, {'op':'move','path':'/definitions','value':{}},
    {'op':'add','path':'/definitions/field'}, {'op':'remove','path':'/definitions','value':None},
    {'op':'add','path':'/source/title/inner','value':1}, {'op':'replace','path':'/definition/field','value':1}])
def test_invalid_pointer_or_authority_edit_is_atomic(operation):
    c=proposal(); before=copy.deepcopy(c)
    with pytest.raises(ValueError):patch(c,[{'op':'add','path':'/definitions/before','value':'must not persist'},operation])
    assert c==before


def test_hash_quantity_bytes_and_reason_limits():
    c=proposal()
    with pytest.raises(ValueError,match='current_contract_sha256'):patch(c,[],expected='0'*64)
    with pytest.raises(ValueError):patch(c,[])
    with pytest.raises(ValueError):patch(c,[{'op':'add','path':'/definitions/a','value':1}]*9)
    with pytest.raises(ValueError,match='16 KiB'):patch(c,[{'op':'add','path':'/definitions/a','value':'a'*16384}])
    with pytest.raises(ValueError):patch(c,[{'op':'add','path':'/definitions/a','value':float('nan')}])
    with pytest.raises(ValueError):patch(c,[{'op':'add','path':'/definitions/a','value':1}],reason='')


def offline_session(tmp_path):
    session=object.__new__(agent.AgentSession)
    path=tmp_path/'input.csv';path.write_text('ID,DATE,DEATHS\n1,2024-01-01,0\n')
    session.files=[{'id':'input','name':path.name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]
    session.work_dir=tmp_path;session.contract=proposal();session.documents={'doc-'+'a'*64:{'document_id':'doc-'+'a'*64}}
    session.code='def adapt(ctx):\n    pass';session.intake=SimpleNamespace();session.public_sources=SimpleNamespace()
    session.native_context=None;session.enforce_native_boundary=lambda:None;session.cancel=lambda:None
    session.usage={'correction_count':0,'model_calls':0,'tool_calls':0,'compute_seconds':0}
    session.sample_gate={'admitted':True};session.validated={'prior':True};session.registered={'version':'old'};session.ready={'old':True}
    return session


def test_tool_uses_normal_validation_and_invalidates_previous_admission(tmp_path, monkeypatch):
    session=offline_session(tmp_path)
    monkeypatch.setattr(agent.store,'connect',lambda *a,**k:pytest.fail('Offline contract tool must not access DB'))
    seen=[];session.enforce_native_boundary=lambda:seen.append(True)
    result=session.execute_tool('patch_source_contract',{'expected_contract_sha256':registry.digest_json(session.contract),
        'patches':[{'op':'add','path':'/resources/0/mapping/fatalities','value':{'field':'DEATHS'}}],'reason':'Source definition supports this count'})
    assert seen==[True] and result['status']=='proposed' and result['patch_count']==1
    assert session.contract['evidence']['date'][0]['document_id']=='doc-'+'a'*64
    assert session.sample_gate is session.validated is session.registered is session.ready is None
    assert session.usage['correction_count']==1


@pytest.mark.parametrize('operation,exception',[
    ({'op':'replace','path':'/source/source_id','value':'bad:id'},ValidationFailure),
    ({'op':'replace','path':'/source/jurisdiction','value':['UNKNOWN']},ValidationFailure),
    ({'op':'replace','path':'/evidence/date/0/document_id','value':'wrong-document'},NeedsInput)])
def test_normal_validation_failure_preserves_contract_but_revokes_stale_gates(tmp_path,operation,exception):
    session=offline_session(tmp_path);before=copy.deepcopy(session.contract)
    with pytest.raises(exception):session.execute_tool('patch_source_contract',{
        'expected_contract_sha256':registry.digest_json(session.contract),'patches':[operation],'reason':'Try correction'})
    assert session.contract==before and session.usage['correction_count']==0
    # A rejected changed proposal cannot accidentally publish prior admission.
    # The saved contract is unchanged, and must receive fresh QA before reuse.
    assert session.sample_gate is session.validated is session.registered is session.ready is None
