import copy
import hashlib
import json
from pathlib import Path
import pytest

from arsia_pipeline.canonical import ContractError, project
from arsia_pipeline.errors import ValidationFailure
from arsia_pipeline.trusted_qa import validate_candidate, semantic_contract


def contract():
    return {'contract_version':'canonical-v2','source':{'source_id':'independent_fixture','jurisdiction':['SA'],
        'publisher':'Synthetic QA test','title':'Hand-authored QA fixture','dataset_url':'https://data.sa.gov.au/fixture','licence':'Synthetic fixture',
        'coverage':{'from':'2020-01-01','to':'2025-12-31'}},'update':{'mode':'snapshot'},'resources':[
        {'role':'crash','file_id':'file1','grain':'crash','key':['ID'],'table':{'format':'csv'},'mapping':{
          'date':{'field':'DATE','formats':['%d/%m/%Y %H:%M'],'precision':'day'},
          'severity':{'field':'SEVERITY','categories':{'F':{'code':'fatal','label':'Fatal','is_fatal_crash':True},'U':{'code':'unknown','label':'Unknown','is_fatal_crash':None}}},
          'fatalities':{'field':'DEATHS'},'casualties':{'sum_fields':['DEATHS','INJURED']}}}],
        'relations':[],'evidence':{},'definitions':{'casualties_includes_fatalities':True}}


RAW={'ID':'001','DATE':'30/04/2024 13:20','SEVERITY':'F','DEATHS':'2','INJURED':'3'}


def test_exact_metrics_lineage_and_native_extensions():
    c=contract();r=project(c,'crash','csv:1',RAW)
    assert (r['record_id'],r['raw_key'],r['occurrence_date'],r['date_precision'])==('["001"]',['001'],'2024-04-30','day')
    assert (r['is_fatal_crash'],r['fatalities'],r['casualties'])==(True,2,5)
    assert r['extensions']==RAW and r['source_id']=='independent_fixture'
    assert len(r['canonical_id'])==64 and r['coordinates'] is None


def test_unknown_fatal_crash_is_not_zero_and_missing_count_is_unknown():
    c=contract();r=project(c,'crash','csv:1',{**RAW,'SEVERITY':'U','DEATHS':''})
    assert r['is_fatal_crash'] is None and r['fatalities'] is None and r['casualties'] is None
    del c['resources'][0]['mapping']['fatalities']
    r=project(c,'crash','csv:1',RAW)
    assert r['fatalities'] is None and r['availability']['fatalities']['status']=='unsupported'


@pytest.mark.parametrize('patch',[{'SEVERITY':'new'},{'ID':''},{'DEATHS':'-1'},{'INJURED':'1.5'},{'DATE':'31/02/2024 01:00'}])
def test_unregistered_or_invalid_source_values_block(patch):
    with pytest.raises(ContractError):project(contract(),'crash','csv:1',{**RAW,**patch})


def test_date_ambiguity_and_explicit_text_month():
    c=contract();c['resources'][0]['mapping']['date']={'field':'DATE','formats':['%d/%m/%Y','%m/%d/%Y']}
    with pytest.raises(ContractError,match='conflicting'):project(c,'crash','1',{**RAW,'DATE':'01/02/2024'})
    c['resources'][0]['mapping']['date']={'year_field':'YEAR','month_field':'MONTH','month_values':{'April':4},'precision':'month'}
    r=project(c,'crash','1',{**RAW,'YEAR':'2024','MONTH':'April'})
    assert (r['occurrence_date'],r['date_precision'],r['month'])==('2024-04','month',4)


def test_epoch_date_uses_official_fixed_timezone_not_host_timezone():
    c=contract();c['resources'][0]['mapping']['date']={'field':'DATE','kind':'epoch_ms','timezone':'Etc/GMT-10'}
    r=project(c,'crash','1',{**RAW,'DATE':1704034800000})
    assert r['occurrence_date']=='2024-01-01'


def test_geography_needs_evidence_and_missing_points_stay_unknown():
    c=contract();c['resources'][0]['mapping']['geography']={'x_field':'X','y_field':'Y','crs':'EPSG:4326'}
    row={**RAW,'X':'147.3','Y':'-42.9'}
    assert project(c,'crash','1',row)['coordinates'] is None
    c['evidence']['geography']=[{'document_id':'mock','quote':'Fixture CRS declaration'}]
    assert project(c,'crash','1',row)['coordinates']==[147.3,-42.9]
    assert project(c,'crash','1',{**row,'X':''})['geography_status']=='unknown'
    with pytest.raises(ContractError):project(c,'crash','1',{**row,'X':'0','Y':'0'})


def test_task_ids_and_evidence_paths_do_not_change_semantic_adapter_identity():
    a=contract();b=copy.deepcopy(a);b['resources'][0]['file_id']='different-upload-id';b['documents']=[{'text_path':'/different/attempt'}]
    assert semantic_contract(a)==semantic_contract(b)


def test_volatile_document_receipt_identity_does_not_republish_identical_rules():
    a=contract();b=copy.deepcopy(a)
    a['documents']=[{'document_id':'old-content-hash','url':'https://data.act.gov.au/api/views/example.json'}]
    b['documents']=[{'document_id':'new-content-hash','url':'https://data.act.gov.au/api/views/example.json'}]
    a['evidence']={'date':[{'document_id':'old-content-hash','quote':'Reported date of crash'}]}
    b['evidence']={'date':[{'document_id':'new-content-hash','quote':'Reported  date of crash'}]}
    assert semantic_contract(a)==semantic_contract(b)
    b['evidence']['date'][0]['quote']='Different date semantics'
    assert semantic_contract(a)!=semantic_contract(b)


def envelope(tmp_path,mutation=None):
    c=contract();f=tmp_path/'events.csv';f.write_text('ID,DATE,SEVERITY,DEATHS,INJURED\n001,30/04/2024 13:20,F,2,3\n')
    file={'id':'file1','name':'events.csv','path':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'size':f.stat().st_size}
    output=tmp_path/'run'/'output';output.mkdir(parents=True)
    row=project(c,'crash','csv:1',RAW)
    if mutation:mutation(row)
    (output/'crashes.jsonl').write_text(json.dumps(row)+'\n')
    for name in ('units','casualties','observations','exclusions'):(output/(name+'.jsonl')).write_text('')
    run={'status':'succeeded','mode':'sample','run_id':'one','code_sha256':'code-sha','output_dir':str(output),
         'contract_sha256':hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
         'artifacts':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in output.iterdir()]}
    return c,file,run


def test_sample_checks_independent_rows_but_never_admits_publication(tmp_path):
    c,f,r=envelope(tmp_path)
    result=validate_candidate(r,c,[f],'code-sha',tmp_path)
    assert result['summary']['fatalities']==2 and result['summary']['casualties']==5
    assert result['admission']['status']=='sample_only'


def test_fabricated_adapter_metric_is_rejected_by_raw_replay(tmp_path):
    c,f,r=envelope(tmp_path,lambda row:row.update(fatalities=99))
    with pytest.raises(ValidationFailure,match='independent'):validate_candidate(r,c,[f],'code-sha',tmp_path)


def test_artifact_modified_after_run_is_rejected(tmp_path):
    c,f,r=envelope(tmp_path);(Path(r['output_dir'])/'crashes.jsonl').write_text('')
    with pytest.raises(ValidationFailure,match='changed'):validate_candidate(r,c,[f],'code-sha',tmp_path)


def test_repeat_qa_can_recover_without_reusing_partial_database(tmp_path):
    c,f,r=envelope(tmp_path)
    first=validate_candidate(r,c,[f],'code-sha',tmp_path)
    again=validate_candidate(r,c,[f],'code-sha',tmp_path)
    assert first['fingerprint']==again['fingerprint']
    assert len(list(tmp_path.glob('trusted-qa-one-*.sqlite')))==2


def test_unproven_global_complete_boolean_cannot_enable_implicit_child_equality(tmp_path, monkeypatch):
    import arsia_pipeline.trusted_qa as qa
    c, f, r = envelope(tmp_path)
    c['definitions']['casualty_table_complete'] = True
    r.update(mode='full', contract_sha256=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest())
    monkeypatch.setattr(qa, '_proof', lambda *_: {'casualty_scope_review': {'ok': True, 'decisions': []}})
    result = validate_candidate(r, c, [f], 'code-sha', tmp_path)
    assert result['summary']['casualties'] == 5


def test_verified_complete_child_scope_enforces_only_its_parent_child_equality(tmp_path, monkeypatch):
    import arsia_pipeline.trusted_qa as qa
    from arsia_pipeline.intakereaders import iter_table
    c, f, r = envelope(tmp_path)
    path = tmp_path / 'people.csv'; path.write_text('ID,PERSON\n001,P1\n')
    child = {'id':'people','name':path.name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    c['resources'].append({'role':'people','file_id':'people','grain':'casualty','key':['ID','PERSON'],'mapping':{},'table':{'format':'csv'}})
    c['relations'].append({'child':'people','parent':'crash','fields':['ID']})
    output = Path(r['output_dir'])
    rows = [project(c, 'people', locator, raw) for locator, raw in iter_table(child, {'format':'csv'})]
    (output/'casualties.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    r.update(mode='full', contract_sha256=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
        artifacts=[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in output.iterdir()])
    monkeypatch.setattr(qa, '_proof', lambda *_: {'casualty_scope_review': {'ok': True, 'decisions': [
        {'parent_role':'crash','resource_role':'people','complete':True}]}})
    with pytest.raises(ValidationFailure, match='Complete casualty register'):
        validate_candidate(r, c, [f,child], 'code-sha', tmp_path)


def test_unassigned_uploaded_child_table_blocks_conservation(tmp_path):
    c,f,r=envelope(tmp_path)
    path=tmp_path/'children.csv';path.write_text('ID,UNIT\n001,U1\n')
    child={'id':'unused','name':path.name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    with pytest.raises(ValidationFailure,match='not assigned a grain'):
        validate_candidate(r,c,[f,child],'code-sha',tmp_path)


def test_day_coverage_cannot_silently_exclude_same_year_rows(tmp_path):
    c,f,r=envelope(tmp_path)
    c['source']['coverage']['to']='2024-04-29'
    r['contract_sha256']=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    with pytest.raises(ValidationFailure,match='coverage excludes'):
        validate_candidate(r,c,[f],'code-sha',tmp_path)


def test_unit_declared_casualty_count_is_checked_independently(tmp_path,monkeypatch):
    import arsia_pipeline.trusted_qa as qa
    from arsia_pipeline.intakereaders import iter_table
    c,f,r=envelope(tmp_path)
    files=[f]
    for role,body,grain,key,mapping in [
        ('unit','ID,UNIT,CAS_COUNT\n001,U1,2\n','unit',['ID','UNIT'],{'declared_casualties':{'field':'CAS_COUNT'}}),
        ('casualty','ID,UNIT,CAS\n001,U1,C1\n','casualty',['ID','UNIT','CAS'],{})]:
        path=tmp_path/(role+'.csv');path.write_text(body)
        files.append({'id':role,'name':path.name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size})
        c['resources'].append({'role':role,'file_id':role,'grain':grain,'key':key,'mapping':mapping,'table':{'format':'csv'}})
        c['relations'].append({'child':role,'parent':'crash','fields':['ID']})
    c['relations'].append({'child':'casualty','parent':'unit','fields':['ID','UNIT']})
    out=Path(r['output_dir'])
    for resource,file in zip(c['resources'],files):
        rows=[project(c,resource['role'],locator,raw) for locator,raw in iter_table(file,resource['table'])]
        (out/qa.ARTIFACT_NAMES[resource['grain']]).write_text(''.join(json.dumps(row)+'\n' for row in rows))
    r.update(mode='full',contract_sha256=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
        artifacts=[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in out.iterdir()])
    monkeypatch.setattr(qa,'_proof',lambda *_:{}) # Synthetic relational test, not official-source admission.
    with pytest.raises(ValidationFailure,match='parent child count'):
        validate_candidate(r,c,files,'code-sha',tmp_path)


def test_native_namespace_requires_host_context_and_rejects_model_json(tmp_path):
    from arsia_pipeline.trusted_qa import validate_contract
    c, f, _ = envelope(tmp_path)
    c['source']['source_id'] = 'official_qld'
    with pytest.raises(ValidationFailure, match='frozen source namespaces'):
        validate_contract(c, [f])
    with pytest.raises(ValidationFailure, match='host-created'):
        validate_contract(c, [f], native_context={'source_id': 'official_qld'})


def test_evidence_diagnostics_distinguish_invalid_quote_from_missing_document(tmp_path, monkeypatch):
    from arsia_pipeline import config
    from arsia_pipeline.trusted_qa import _proof
    from arsia_pipeline.errors import NeedsInput
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    content = b'Official crash catalogue with explicit source field definitions.'
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path/'sha256').mkdir()
    (tmp_path/'sha256'/sha).write_bytes(content)
    receipt = tmp_path/'receipt.json'
    receipt.write_text(json.dumps({'status':'fetched','final_url':'https://data.example.gov.au/catalog',
        'final_host_official':True,'sha256':sha}))
    c = contract()
    c['documents'] = [{'document_id':'verified-doc','receipt_path':str(receipt)}]
    c['evidence']['date'] = [{'document_id':'verified-doc','quote':'Invented date field definition'}]
    c['evidence']['grain'] = [{'document_id':'unknown-doc','quote':'Some unsupported grain description'}]
    with pytest.raises(NeedsInput) as error:
        _proof(c, tmp_path)
    rejected = {v['claim']:v['reason'] for v in error.value.details['rejected_evidence']}
    assert rejected == {'date':'quote_not_exact','grain':'document_not_verified'}
    assert error.value.details['verified_documents'] == [{'document_id':'verified-doc','url':'https://data.example.gov.au/catalog'}]
    assert str(tmp_path) not in json.dumps(error.value.details)


def test_crashes_without_source_severity_keep_count_and_unknown_classification():
    c = contract()
    del c['resources'][0]['mapping']['severity']
    row = project(c, 'crash', 'csv:1', RAW)
    assert row['severity'] == 'unavailable' and row['raw_severity'] is None
    assert row['is_fatal_crash'] is None
    assert row['availability']['severity']['status'] == 'unsupported'
    assert row['fatalities'] == 2


def test_unassigned_json_record_collection_cannot_be_replaced_by_download(tmp_path):
    c, f, r = envelope(tmp_path)
    path = tmp_path/'uploaded.json'
    path.write_text(json.dumps({'features':[{'attributes':{'ID':1,'YEAR':2024}}]}))
    uploaded = {'id':'json-upload','name':path.name,'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'size':path.stat().st_size}
    with pytest.raises(ValidationFailure, match='not assigned a grain'):
        validate_candidate(r, c, [f,uploaded], 'code-sha', tmp_path)


def test_optional_plaintext_and_dictionary_are_not_fake_fact_tables(tmp_path):
    from arsia_pipeline.trusted_qa import validate_contract
    c,f,_=envelope(tmp_path)
    files=[f]
    for name,content in [('notes.txt','Publisher data dictionary\nCoverage notes are supplied here\n'),('dictionary.csv','field,description\nID,Official source identifier\n')]:
        path=tmp_path/name;path.write_text(content)
        files.append({'id':name,'name':name,'path':str(path),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    assert validate_contract(c,files)['crash']['file_id']=='file1'


def test_unassigned_worksheet_cannot_silently_disappear(tmp_path):
    from openpyxl import Workbook
    from arsia_pipeline.trusted_qa import validate_contract
    path=tmp_path/'multiple.xlsx';book=Workbook();book.active.title='Events'
    book.active.append(['ID','DATE','SEVERITY','DEATHS','INJURED'])
    book.create_sheet('People').append(['ID','PERSON'])
    book.save(path)
    file={'id':'file1','name':path.name,'path':str(path),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    c=contract();c['resources'][0]['table']={'format':'xlsx','sheet':'Events'}
    with pytest.raises(ValidationFailure,match='not assigned a grain') as error:
        validate_contract(c,[file])
    assert error.value.qa[0]['metrics']['table_id']=='People'


def test_coordinate_canonicalization_removes_platform_ulps_without_changing_raw(monkeypatch):
    from arsia_pipeline import canonical, transform_plan
    spec={'x_field':'X','y_field':'Y','crs':'EPSG:8059'}
    raw={'X':'1321740','Y':'1689490'}
    points=[]
    for epsilon in [0.0,7.105427357601002e-15]:
        monkeypatch.setattr(transform_plan,'transform',lambda crs,x,y:(138.61234567891234,-34.92345678912345+epsilon,'fixture-operation'))
        value=canonical.geography(raw,spec,True)
        assert value['raw_coordinates']==['1321740','1689490']
        points.append(value['coordinates'])
    assert points[0]==points[1]==[138.61234568,-34.92345679]


def test_projection_difference_is_diagnostic_only_and_never_exposes_source_values():
    from arsia_pipeline.trusted_qa import projection_difference
    expected={'coordinates':[138.6,-34.9],'fatalities':1,'extensions':{'person':'sensitive'}}
    actual={'coordinates':[138.60000001,-34.9],'fatalities':2,'extensions':{'person':'different'},'private_value_as_key':0}
    report=projection_difference(expected,actual)
    assert report['differing_fields']==['coordinates','extensions','fatalities','<unexpected_field>']
    assert report['coordinate_absolute_delta_degrees'][0]>0
    assert report['expected_sha256']!=report['candidate_sha256']
    assert not any(value in json.dumps(report) for value in ['sensitive','different','private_value_as_key'])


@pytest.mark.parametrize('field,value', [('extensions', {'ID':'forged'}), ('raw_key',['forged']),
    ('coordinates',[138.1,-34.1]), ('source_id','forged'), ('relations',{'absent':'forged'})])
def test_compact_qa_still_checks_every_full_row_field(tmp_path, field, value):
    c,f,r=envelope(tmp_path,lambda row:row.update({field:value}))
    with pytest.raises(ValidationFailure,match='independent'):
        validate_candidate(r,c,[f],'code-sha',tmp_path)


def test_compact_qa_scratch_has_full_row_digest_without_duplicate_payload(tmp_path):
    import sqlite3
    from arsia_pipeline.trusted_qa import row_digest
    c,f,r=envelope(tmp_path)
    validate_candidate(r,c,[f],'code-sha',tmp_path)
    scratch=next(tmp_path.glob('trusted-qa-*.sqlite'))
    with sqlite3.connect(scratch) as db:
        payload,digest=db.execute('SELECT payload,row_sha256 FROM verified').fetchone()
        assert 'extensions' not in json.loads(payload)
        assert digest==row_digest(project(c,'crash','csv:1',RAW))
        assert [x[1] for x in db.execute('PRAGMA table_info(candidate)')]==['role','locator']
