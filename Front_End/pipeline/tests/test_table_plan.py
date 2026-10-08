import copy
import hashlib
import json
from pathlib import Path

import pytest

from arsia_pipeline.canonical import project
from arsia_pipeline.errors import ImportCancelled, UnsupportedCapability, ValidationFailure
from arsia_pipeline.table_plan import iter_resource, prepare_union, physical_resources
from arsia_pipeline.trusted_qa import validate_contract, validate_candidate, semantic_contract
from test_canonical_v2 import contract, RAW


def bundle(tmp_path, duplicate_key=False, reordered=False):
    c=contract()
    texts=['ID,DATE,SEVERITY,DEATHS,INJURED\n001,30/04/2024 13:20,F,2,3\n',
           'ID,DATE,SEVERITY,DEATHS,INJURED\n'+('001' if duplicate_key else '002')+',01/05/2024 13:20,U,0,1\n']
    if reordered:
        texts[1]='INJURED,DEATHS,SEVERITY,DATE,ID\n1,0,U,01/05/2024 13:20,002\n'
    files=[]
    for i,text in enumerate(texts):
        p=tmp_path/f'part{i}.csv';p.write_text(text)
        files.append({'id':f'file{i+1}','name':p.name,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size})
    c['resources'][0]['partitions']=[{'file_id':f['id'],'table':{'format':'csv'}} for f in files]
    return c,files


def candidate(tmp_path,c,files,omit=False):
    output=tmp_path/'output';output.mkdir()
    rows=[project(c,'crash',locator,row) for locator,row in iter_resource(c['resources'][0],files)]
    if omit:rows=rows[:1]
    (output/'crashes.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    for name in ('units','casualties','observations','exclusions'):(output/(name+'.jsonl')).write_text('')
    return {'status':'succeeded','mode':'sample','run_id':'union','code_sha256':'fixture','output_dir':str(output),
            'contract_sha256':hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
            'artifacts':[{'name':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in output.iterdir()]}


def test_union_preserves_physical_lineage_and_business_keys(tmp_path):
    c,files=bundle(tmp_path,reordered=True)
    selected,plan=prepare_union(c['resources'][0],files)
    rows=list(iter_resource(c['resources'][0],files))
    assert len(rows)==2
    assert [json.loads(locator)[1:] for locator,_ in rows]==[[f['sha256'],'default','csv:1'] for f in files]
    assert project(c,'crash',rows[0][0],rows[0][1])['canonical_id']==project(contract(),'crash','csv:1',RAW)['canonical_id']
    assert rows[1][1]['ID']=='002'
    assert plan['operation']=='union_all' and len(plan['inputs'])==2
    receipts=[];validate_contract(c,files,table_receipts=receipts)
    assert len([r for r in receipts if r['purpose']=='fact'])==2
    assert next(r for r in receipts if r['purpose']=='logical_union')['plan']==plan
    run=candidate(tmp_path,c,files)
    result=validate_candidate(run,c,files,'fixture',tmp_path)
    assert result['summary']['crash_count']==2
    assert result['evidence']['input_counts']=={'crash':2}
    assert result['admission']['evidence']['parser_plans']['crash']['union_plan']==plan


@pytest.mark.parametrize('fault',['duplicate_key','omitted_partition'])
def test_full_logical_key_and_conservation_checks_cover_all_partitions(tmp_path,fault):
    c,files=bundle(tmp_path,duplicate_key=fault=='duplicate_key')
    run=candidate(tmp_path,c,files,omit=fault=='omitted_partition')
    with pytest.raises(ValidationFailure):validate_candidate(run,c,files,'fixture',tmp_path)


@pytest.mark.parametrize('fault',['primary_mismatch','unknown_file','duplicate_table','override_mapping','empty_plan','filter'])
def test_union_selection_cannot_rebind_drop_or_duplicate_physical_tables(tmp_path,fault):
    c,files=bundle(tmp_path);r=c['resources'][0]
    if fault=='primary_mismatch':r['file_id']='file2'
    if fault=='unknown_file':r['partitions'][1]['file_id']='unadmitted'
    if fault=='duplicate_table':
        files[1]={**files[0],'id':'file2','name':'renamed.csv'}
    if fault=='override_mapping':r['partitions'][1]['mapping']={}
    if fault=='empty_plan':r['partitions']=[]
    if fault=='filter':r['partitions'][1]['table']['skipRows']=1
    with pytest.raises((UnsupportedCapability,ValidationFailure)):validate_contract(c,files)


def test_union_schema_drift_is_explicit_capability_block(tmp_path):
    c,files=bundle(tmp_path)
    p=Path(files[1]['path']);p.write_text(p.read_text().replace('INJURED','Different population'))
    files[1].update(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size=p.stat().st_size)
    with pytest.raises(UnsupportedCapability) as exc:validate_contract(c,files)
    assert exc.value.code=='UNION_SCHEMA_DRIFT_UNSUPPORTED'


def test_renamed_upload_ids_do_not_change_semantic_contract_or_lineage(tmp_path):
    c,files=bundle(tmp_path)
    renamed=copy.deepcopy(c);renamed['resources'][0]['file_id']='new1'
    for i,part in enumerate(renamed['resources'][0]['partitions']):part['file_id']=f'new{i+1}'
    uploads=[{**f,'id':f'new{i+1}','name':'renamed'+str(i)} for i,f in enumerate(files)]
    assert semantic_contract(c)==semantic_contract(renamed)
    assert list(iter_resource(c['resources'][0],files))==list(iter_resource(renamed['resources'][0],uploads))


def test_union_cancellation_and_unassigned_extra_input(tmp_path):
    c,files=bundle(tmp_path)
    def stop():raise ImportCancelled()
    with pytest.raises(ImportCancelled):list(iter_resource(c['resources'][0],files,stop))
    p=tmp_path/'extra.csv';p.write_text('ID,Unassigned\n3,Preserve\n')
    files.append({'id':'extra','name':p.name,'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'size':p.stat().st_size})
    with pytest.raises(ValidationFailure,match='not assigned a grain'):validate_contract(c,files)


def test_one_partition_receipt_cannot_authorize_deletion_from_union(tmp_path):
    from arsia_pipeline.source_completeness import review_completeness
    c,files=bundle(tmp_path)
    report=review_completeness(c,files,{}, {},root=tmp_path)
    assert report['resources'][0]['status']=='unproven'
    assert 'Union row conservation' in report['resources'][0]['reason']


def test_second_partition_geometry_cannot_borrow_first_crs(tmp_path):
    from arsia_pipeline.errors import NeedsInput
    c,files=bundle(tmp_path)
    for i,file in enumerate(files):
        data={'type':'FeatureCollection','features':[{'type':'Feature','properties':{**RAW,'ID':str(i)},
                                                     'geometry':{'type':'Point','coordinates':[149.1,-35.2]}}]}
        if i:data['crs']={'type':'name','properties':{'name':'EPSG:3857'}}
        p=Path(file['path']);p.write_text(json.dumps(data));file.update(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),size=p.stat().st_size)
    resource=c['resources'][0];resource['table']={}
    for part in resource['partitions']:part['table']={}
    resource['mapping']['geography']={'x_field':'__geometry_x','y_field':'__geometry_y','crs':'EPSG:4326'}
    with pytest.raises(NeedsInput) as exc:validate_contract(c,files)
    assert exc.value.details['blockers'][0]['code']=='GEOMETRY_CRS_CONFLICT'
