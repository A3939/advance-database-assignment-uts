"""Independent literal oracle for restricted spatial capability, not real-source acceptance."""
import hashlib
import json
from pathlib import Path
import pytest
from arsia_pipeline import config
from arsia_pipeline.capability_limits import geography_limited
from arsia_pipeline.capability_preflight import geometry_blockers
from arsia_pipeline.errors import ValidationFailure
from arsia_pipeline.isolated_executor import run_python
from arsia_pipeline.trusted_qa import validate_candidate


def source_fixture(root):
    dictionary_url='https://data.example.gov.au/dictionary.pdf'
    text='ID identifies a reported event. DATE records the event date. Event_X Event_Y\nCoordinate system for Event_X and Event_Y is not documented.'
    catalogue=json.dumps({'result':{'name':'events','notes':'Reported event data; temporal completeness not established','resources':[{'url':dictionary_url},{'url':'https://data.example.gov.au/events.csv'}]}})
    c={'contract_version':'canonical-v2','source':{'source_id':'limited_fixture','publisher':'Synthetic fixture','title':'Limited map fixture','dataset_url':'https://data.example.gov.au/dataset/events','jurisdiction':['ACT'],'grain':'crash','coverage':{'from':'2024-01-01','to':'2024-12-31'},'licence':None},
       'update':{'mode':'snapshot'},'resources':[{'role':'events','grain':'crash','file_id':'uploaded','key':['ID'],'table':{'format':'csv'},'mapping':{'date':{'field':'DATE','formats':['%Y-%m-%d']}},'capability_limits':{'geography':{'requested':True,'reason':'Raw coordinates require a reviewed transformation before map use.'}}}],
       'documents':[],'relations':[],'definitions':{}}
    (root/'sha256').mkdir()
    for key,url,content in [('dictionary',dictionary_url,text),('catalogue','https://data.example.gov.au/api/3/action/package_show?id=events',catalogue)]:
        sha=hashlib.sha256(content.encode()).hexdigest();(root/'sha256'/sha).write_text(content)
        receipt=root/(key+'.json');receipt.write_text(json.dumps({'status':'fetched','final_url':url,'sha256':sha,'final_host_official':True}))
        c['documents'].append({'document_id':key,'receipt_path':str(receipt),'url':url,'sha256':sha})
    c['evidence']={claim:[{'document_id':'dictionary','quote':text}] for claim in ('grain','date')}
    c['evidence'].update({claim:[{'document_id':'catalogue','quote':catalogue}] for claim in ('source_identity','coverage_update')})
    path=root/'input.csv';path.write_text('ID,DATE,Event_X,Event_Y,Note\n001,2024-01-01,123,456,Unexplained extra field\n')
    files=[{'id':'uploaded','path':str(path),'name':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}]
    from source_binding_fixture import add_reference
    add_reference(files,root)
    return c,files


@pytest.mark.parametrize('mode',['sample','full'])
@pytest.mark.parametrize('invent_map',[False,True])
def test_real_execution_retains_raw_coordinates_but_cannot_claim_unverified_map(tmp_path,monkeypatch,mode,invent_map):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=source_fixture(tmp_path)
    code='def adapt(ctx):\n    for loc,raw in ctx.iter_rows("events"):\n        out=ctx.project("events",loc,raw)\n'
    if invent_map:code+='        out["coordinates"]=[150,-35]\n        out["geography_status"]="available"\n'
    code+='        ctx.emit("crash",out)\n'
    run=run_python(code,files,tmp_path/'runs',source_contract=c,mode=mode,limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded',run
    if invent_map:
        with pytest.raises(ValidationFailure,match='independent raw-row projection'):validate_candidate(run,c,files,run['code_sha256'],tmp_path)
        return
    result=validate_candidate(run,c,files,run['code_sha256'],tmp_path)
    rows=[json.loads(v) for v in (Path(run['output_dir'])/'crashes.jsonl').read_text().splitlines()]
    assert len(rows)==1 and rows[0]['record_id']=='["001"]' and rows[0]['occurrence_date']=='2024-01-01'
    assert rows[0]['coordinates'] is None and rows[0]['extensions']['Event_X']=='123' and rows[0]['extensions']['Note']=='Unexplained extra field'
    assert result['summary']['crash_count']==1 and result['summary']['fatalities'] is None
    assert result['capabilities']['map_points'] is False
    assert result['capability_limits'][0]['target_satisfied'] is False
    assert result['licensing']['resources'][0]['status']=='unknown'


def test_restriction_cannot_coexist_with_a_guessed_coordinate_plan():
    resource={'capability_limits':{'geography':{'requested':True,'reason':'Unverified coordinate metadata'}},'mapping':{}}
    assert geometry_blockers(resource,{'json_kind':'arcgis','observed_geometry_types':['Point']})==[]
    resource['mapping']['geography']={'crs':'EPSG:4326'}
    with pytest.raises(ValidationFailure):geography_limited(resource)
