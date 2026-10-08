"""End-to-end host admission with explicit synthetic publisher receipts.

No fetch mocking claims a real source is admitted. Projection/reconciliation
expectations are hand-authored independently of the shared projector.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from arsia_pipeline import config
from arsia_pipeline.errors import NeedsInput, UnsupportedCapability
from arsia_pipeline.evidence_references import reference
from arsia_pipeline.trusted_qa import _proof, validate_candidate
from test_lookup_evidence import fixture, replace, SOURCE, CHILD, PARENT
from test_lookup_projection import bundle
from test_lookup_qa import candidate, sha

CODE = 'def adapt(ctx):\n    for locator, raw in ctx.iter_rows("crash"):\n        ctx.emit("crash", ctx.project("crash", locator, raw))\n'


def configure_admissible(c, files, root):
    _, docs, accepted = fixture()
    c['source'].update(dataset_url=SOURCE,coverage={'from':'2024-01-01','to':'2024-12-31'})
    r=c['resources'][0];r['source_url']=CHILD
    c['lookup_tables'][0]['source_url']=PARENT
    r['lookups'][0]['select'].append('Injured')
    r['mapping']['casualties']={'sum_fields':[{'lookup':'code','field':f} for f in ('Deaths','Injured')]}
    parent=Path(files[1]['path']);parent.write_text('Code,Class,Deaths,Injured,X,Y\nA,F,2,3,149.1,-35.2\nB,U,0,1,149.2,-35.3\n')
    files[1].update(sha256=sha(parent),size=parent.stat().st_size)
    value=json.loads(docs['parent']['content_bytes'])
    value['fields']=[{'name':'Code'},
        {'name':'Class','domain':{'type':'codedValue','codedValues':[{'code':'F','name':'Fatal'},{'code':'U','name':'Unknown'}]}},
        {'name':'X','description':'Longitude coordinate of the crash'},
        {'name':'Y','description':'Latitude coordinate of the crash'},
        {'name':'Deaths','description':'Number of fatalities per crash'},
        {'name':'Injured','description':'Number of injured persons per crash'},
        {'name':'Total','description':'Total casualties = Deaths + Injured'}]
    replace(docs,'parent',value)
    for claim in accepted:
        accepted[claim]=[{'document_id':k,'quote':v['text']} for k,v in docs.items()]
    accepted['counts']=[{'document_id':'parent','quote':docs['parent']['text']}]
    accepted['relations'].append(reference(docs['relations']['content_bytes'],docs['relations']['sha256'],'relations',{'kind':'json-pointer','pointer':''}))
    c['evidence']=accepted
    install_documents(c,docs,root)
    from source_binding_fixture import add_reference
    add_reference(files,root,CHILD,index=0)
    add_reference(files,root,PARENT,index=1)
    return docs


def install_documents(c,docs,root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    objects=root/'sha256';objects.mkdir(exist_ok=True)
    c['documents']=[]
    for key,doc in docs.items():
        (objects/doc['sha256']).write_bytes(doc['content_bytes'])
        receipt=root/(key+'.json')
        receipt.write_text(json.dumps({'status':'fetched','final_url':doc['url'],'sha256':doc['sha256'],'final_host_official':key=='catalogue'}))
        c['documents'].append({'document_id':key,'receipt_path':str(receipt)})


@pytest.mark.parametrize('mode',['sample','full'])
def test_full_semantic_reviews_reach_real_host_lookup_admission(tmp_path,monkeypatch,mode):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files,run=candidate(tmp_path,mode,lambda c,files:configure_admissible(c,files,tmp_path/'evidence'))
    result=validate_candidate(run,c,files,'fixture',tmp_path)
    assert result['admission']['status']==('admitted' if mode=='full' else 'sample_only')
    evidence=result['admission']['evidence']
    assert evidence['lookup_relation_review']['ok'] and evidence['lookup_geography_subject_review']['ok']
    assert evidence['count_operation_review']['ok'] and evidence['category_review']['ok']
    assert evidence['transform_plans']['host'] and evidence['transform_plans']['executor']
    assert result['summary']['crash_count']==2 and result['summary']['fatalities']==2
    assert result['summary']['fatal_crash_count'] is None
    assert result['summary']['casualties']==6 and result['summary']['raw_lookup_record_count']==2
    rows=[json.loads(line) for line in Path(result['canonical_path']).read_text().splitlines()]
    assert [(r['occurrence_date'],r['fatalities'],r['casualties'],r['coordinates']) for r in rows]==[
        ('2024-04-30',2,5,[149.1,-35.2]),('2024-05-01',0,1,[149.2,-35.3])]
    assert evidence['lookup_replay']['admission'] is False  # The physical receipt alone is not admission.


@pytest.mark.parametrize('fault',['relation','coordinate_subject','counts','category','parent_date'])
def test_admission_rejects_specific_semantic_failures(tmp_path,monkeypatch,fault):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=bundle(tmp_path);docs=configure_admissible(c,files,tmp_path/'evidence')
    if fault=='relation':c['evidence']['relations']=[]
    if fault=='coordinate_subject':
        value=json.loads(docs['parent']['content_bytes']);value['fields'][2]['description']='Longitude coordinate of the area centroid';replace(docs,'parent',value)
    if fault=='counts':
        c['resources'][0]['mapping']['casualties']['sum_fields'][1]='INJURED'
        value=json.loads(docs['child']['content_bytes']);value['fields'].append({'name':'INJURED','description':'Number of injured persons per crash'});replace(docs,'child',value)
        for entries in c['evidence'].values():
            for entry in entries:
                if entry.get('document_id')=='child':entry['quote']=docs['child']['text']
        c['evidence']['counts'].append({'document_id':'child','quote':docs['child']['text']})
        install_documents(c,docs,tmp_path/'evidence')
    if fault=='category':
        value=json.loads(docs['parent']['content_bytes']);value['fields'][1].pop('domain');replace(docs,'parent',value)
    if fault=='parent_date':
        r=c['resources'][0];r['lookups'][0]['select'].append('DATE');r['mapping']['date']['field']={'lookup':'code','field':'DATE'}
        value=json.loads(docs['parent']['content_bytes']);value['fields'].append({'name':'DATE'});replace(docs,'parent',value)
    if fault in {'coordinate_subject','category','parent_date'}:
        for entries in c['evidence'].values():
            for entry in entries:
                if entry.get('document_id')=='parent':entry['quote']=docs['parent']['text']
        install_documents(c,docs,tmp_path/'evidence')
    with pytest.raises(NeedsInput) as error:_proof(c,tmp_path,files)
    details=error.value.details
    if fault=='coordinate_subject':assert details['lookup_geography_subject_review']['issues'][0]['code']=='LOOKUP_GEOGRAPHY_SUBJECT_CONFLICT'
    if fault=='counts':assert details['count_operation_review']['issues'][0]['code']=='LOOKUP_CROSS_RESOURCE_SUM_UNSUPPORTED'
    if fault=='category':assert error.value.code=='LOOKUP_CATEGORY_SEMANTICS_UNSUPPORTED'
    if fault=='parent_date':assert error.value.code=='LOOKUP_DATE_SEMANTICS_UNSUPPORTED'
    assert not list(tmp_path.glob('trusted-qa-*.json'))
