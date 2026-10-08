"""Exact embedded resource schemas; fixtures do not authorize a publisher."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.evidence_scope import build_applicability, schema_subjects
from arsia_pipeline.evidence_grounding import ground_contract
from arsia_pipeline.evidence_references import reference
from arsia_pipeline.count_semantics import review_count_operations
from arsia_pipeline.category_evidence import review_categories
from arsia_pipeline.geography_review import coordinate_subject, review_lookup_geography_subject
from test_lookup_evidence import fixture, replace, document, SOURCE, CHILD, PARENT


def embedded():
    c, docs, accepted = fixture()
    c['resources'][0]['mapping']['fatalities'] = {'field': {'lookup': 'code', 'field': 'Deaths'}}
    c['resources'][0]['lookups'][0]['select'].append('Deaths')
    c['resources'][0]['mapping']['severity']['categories'] = {'F': {'code':'fatal','label':'Fatal','is_fatal_crash':True}}
    child = {'id':'events','url':CHILD,'attributes':[{'db_name':f,'name':f} for f in ['ID','DATE','Type']]}
    parent = {'id':'codes','url':PARENT,'attributes':[
        {'db_name':'Code','name':'Code'},
        {'db_name':'X','name':'Longitude','definition':'Longitude coordinate of the crash'},
        {'db_name':'Y','name':'Latitude','definition':'Latitude coordinate of the crash'},
        {'db_name':'Deaths','name':'Deaths','definition':'Number of fatalities per crash'}],
        'fields':[{'name':'Class','domain':{'type':'codedValue','codedValues':[{'code':'F','name':'Fatal'}]}}]}
    # Other publisher resources deliberately have incompatible same-named fields.
    neighbour = {'id':'other','url':PARENT+'?year=2010','attributes':[
        {'db_name':'X','definition':'Longitude coordinate of the station'},
        {'db_name':'Y','definition':'Latitude coordinate of the station'},
        {'db_name':'Deaths','definition':'Number of injured persons per crash'}],
        'fields':[{'name':'Class','domain':{'type':'codedValue','codedValues':[{'code':'F','name':'Injury'}]}}]}
    replace(docs,'catalogue',{'result':{'name':'events','resources':[child,parent,neighbour,
        {'id':'geo','url':PARENT,'metadata_url':docs['geo']['url']},
        {'id':'relation','url':CHILD,'metadata_url':docs['relations']['url']}]}})
    docs.pop('child');docs.pop('parent')
    for claim in accepted:
        accepted[claim]=[{'document_id':k,'quote':v['text']} for k,v in docs.items()]
    accepted['counts']=[{'document_id':'catalogue','quote':docs['catalogue']['text']}]
    return c,docs,accepted


def evaluate(c,d,a):
    graph=build_graph(SOURCE,d,{'catalogue'})
    g=ground_contract(c,d,a,graph=graph)
    return graph,g


def test_embedded_schema_uses_exact_resource_and_native_attribute_alias():
    c,d,a=embedded();graph,g=evaluate(c,d,a)
    assert g['ok'],g
    assert review_count_operations(c,d,g,a,graph)['ok']
    assert review_categories(c,graph,g,a)['ok']
    result=review_lookup_geography_subject(c,d,g,a,graph)
    assert result['ok'],result
    assert result['decisions'][0]['evidence'][0]['schema_pointer']=='/result/resources/1/attributes/1/definition'
    binding=next(b for b in g['field_bindings'] if b['role']=='codes' and b['field']=='X')
    assert binding['evidence'][0]['official_field']=='X'
    assert next(e for e in binding['evidence'] if e['mode']=='official_structured_field')['aliases']==['Longitude','X']


@pytest.mark.parametrize('change',['no_url','query','neighbour_quote','child_quote','unknown_field'])
def test_embedded_schema_needs_exact_resource_field_and_citation(change):
    c,d,a=embedded()
    if change=='no_url':c['lookup_tables'][0].pop('source_url')
    if change=='query':c['lookup_tables'][0]['source_url']=PARENT+'?year=2009'
    if change in {'neighbour_quote','child_quote'}:
        pointer='/result/resources/'+('2' if change=='neighbour_quote' else '0')
        a['counts']=[reference(d['catalogue']['content_bytes'],d['catalogue']['sha256'],'catalogue',{'kind':'json-pointer','pointer':pointer})]
    if change=='unknown_field':c['resources'][0]['mapping']['fatalities']['field']['field']='Typo'
    if change=='unknown_field':c['resources'][0]['lookups'][0]['select'].append('Typo')
    graph,g=evaluate(c,d,a)
    assert not g['ok']


def test_selected_resource_without_field_cannot_borrow_parent_package_schema():
    c,d,a=embedded();v=json.loads(d['catalogue']['content_bytes'])
    v['result']['fields']=[{'name':'Deaths','description':'Number of fatalities per crash'}]
    v['result']['resources'][1]['attributes'].pop()
    replace(d,'catalogue',v)
    assert not evaluate(c,d,a)[1]['ok']


@pytest.mark.parametrize('group',['count','category','coordinate'])
def test_duplicate_exact_resource_descriptors_preserve_uncited_conflicts(group):
    c,d,a=embedded();v=json.loads(d['catalogue']['content_bytes'])
    other=copy.deepcopy(v['result']['resources'][2]);other['url']=PARENT
    v['result']['resources'].append(other);replace(d,'catalogue',v)
    graph,g=evaluate(c,d,a)
    if group=='count':result=review_count_operations(c,d,g,a,graph)
    elif group=='category':result=review_categories(c,graph,g,a)
    else:result=review_lookup_geography_subject(c,d,g,a,graph)
    assert not result['ok'],result
    assert any('CONFLICT' in issue['code'] for issue in result['issues'])


@pytest.mark.parametrize('statement',['Longitude coordinate of the crash if known','Example: Longitude coordinate of the crash',
    'Longitude coordinate of the crash; actually area centroid','Not the longitude coordinate of the crash',
    'WGS84 longitude', 'Longitude coordinate of an unknown object'])
def test_geographic_meaning_does_not_use_substring_or_crs_as_subject(statement):
    assert coordinate_subject(statement) is None


@pytest.mark.parametrize('change',['axes','station','unknown','uncited','partial_locator'])
def test_projected_parent_position_requires_output_subject_and_cited_definition(change):
    c,d,a=embedded();v=json.loads(d['catalogue']['content_bytes'])
    attrs=v['result']['resources'][1]['attributes']
    if change=='axes':attrs[1]['definition']='Latitude coordinate of the crash'
    if change=='station':attrs[1]['definition']='Longitude coordinate of the station'
    if change=='unknown':attrs[1]['definition']='A coordinate for an unidentified feature'
    replace(d,'catalogue',v)
    if change in {'uncited','partial_locator'}:
        a['geography']=[{'document_id':'geo','quote':d['geo']['text']}]
        if change=='partial_locator':a['geography'].append(reference(d['catalogue']['content_bytes'],d['catalogue']['sha256'],'catalogue',{'kind':'json-pointer','pointer':'/result/resources/1/attributes/1/db_name'}))
    graph,g=evaluate(c,d,a)
    result=review_lookup_geography_subject(c,d,g,a,graph)
    assert not result['ok'],result


def test_native_record_attributes_are_not_treated_as_schema():
    # The supported extension needs db_name, not arbitrary GeoJSON attributes.
    from arsia_pipeline.evidence_grounding import _schemas
    assert _schemas({'attributes':[{'name':'X','value':149}]})==({},False)


def frozen_vic_context():
    root=Path(__file__).resolve().parents[1]/'arsia_pipeline/knowledge/evidence'
    sha='b49db512d35f455a0172f45db29006e9cfc5cec44c0f986995f08fe57e0f2580'
    raw=(root/sha).read_bytes();assert hashlib.sha256(raw).hexdigest()==sha
    value=json.loads(raw);resources=value['result']['resources']
    url='https://opendata.transport.vic.gov.au/api/3/action/package_show?id=victoria-road-crash-data'
    source='https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data'
    d={'official':{'url':url,'sha256':sha,'content_bytes':raw,'text':raw.decode()}}
    c={'source':{'dataset_url':source,'coverage':{'from':'2020-01-01','to':'2024-12-31'}},
       'resources':[{'role':'crash','grain':'crash','file_id':'child','source_url':resources[0]['url'],'key':['ACCIDENT_NO'],
        'lookups':[{'name':'node','parent':'nodes','fields':['NODE_ID'],'select':['LONGITUDE','LATITUDE'],'on_missing':'error','allow_blank':False}],
        'mapping':{'geography':{'x_field':{'lookup':'node','field':'LONGITUDE'},'y_field':{'lookup':'node','field':'LATITUDE'},'crs':'EPSG:4326'}}}],
       'lookup_tables':[{'role':'nodes','file_id':'parent','source_url':resources[4]['url'],'key':['NODE_ID']}]}
    graph=build_graph(source,d,{'official'});assert graph['anchors']=={'official'}
    grounding={'applicability':build_applicability(c,graph)}
    assert not grounding['applicability']['issues']
    a={'geography':[reference(raw,sha,'official',{'kind':'json-pointer','pointer':f'/result/resources/4/attributes/{i}/definition'}) for i in (7,8)]}
    return c,d,grounding,a,graph


def test_actual_frozen_vic_node_definitions_identify_crash_coordinates():
    c,d,grounding,a,graph=frozen_vic_context()
    review=review_lookup_geography_subject(c,d,grounding,a,graph)
    assert review['ok'],review
    assert {(x['field'],x['axis'],x['subject']) for x in review['decisions']}=={('LONGITUDE','x','crash'),('LATITUDE','y','crash')}
    # This proves only the two frozen publisher definitions. No CRS, actual key
    # uniqueness, full-record relation, adapter admission or publication claim.


def test_receipt_verified_proof_reaches_semantics_but_is_not_candidate_admission(tmp_path,monkeypatch):
    import arsia_pipeline.config as config
    from arsia_pipeline.trusted_qa import _proof
    from arsia_pipeline.errors import UnsupportedCapability
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,d,a=embedded();c['evidence']=a;c['documents']=[]
    objects=tmp_path/'sha256';objects.mkdir()
    for key,doc in d.items():
        (objects/doc['sha256']).write_bytes(doc['content_bytes'])
        receipt=tmp_path/(key+'.json')
        receipt.write_text(json.dumps({'status':'fetched','final_url':doc['url'],'sha256':doc['sha256'],'final_host_official':key=='catalogue'}))
        c['documents'].append({'document_id':key,'receipt_path':str(receipt)})
    relation=d['relations']
    c['evidence']['relations'].append(reference(relation['content_bytes'],relation['sha256'],'relations',{'kind':'json-pointer','pointer':''}))
    proof=_proof(c,tmp_path)
    result=proof['lookup_geography_subject_review']
    assert result['ok'] and len(result['decisions'])==2
    assert proof['count_operation_review']['ok']
    assert 'admission' not in proof  # Preflight proof is not sample/full QA.
