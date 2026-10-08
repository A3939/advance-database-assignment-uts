import copy
import hashlib
import json

import pytest

from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.evidence_grounding import ground_contract
from arsia_pipeline.evidence_scope import build_applicability
from arsia_pipeline.metadata_extractors import MetadataError

SOURCE='https://data.example.gov.au/dataset/events'
DATA='https://cdn.example/events.csv'


def document(url,value):
    raw=json.dumps(value).encode()
    return {'url':url,'text':raw.decode(),'content_bytes':raw}


def fixture():
    catalogue={'result':{'name':'events','resources':[
        {'id':'old','url':DATA,'metadata_url':'https://cdn.example/dictionary-old.json'},
        {'id':'new','url':DATA,'metadata_url':'https://cdn.example/dictionary-new.json'}]}}
    old={'@context':'https://schema.org','@type':'DigitalDocument','about':DATA,'version':'1',
         'temporalCoverage':'2015-01-01/2020-01-01','geometryType':'esriGeometryPoint',
         'spatialReference':{'wkid':4283},'fields':[{'name':'ID'},{'name':'DATE'}]}
    new={**old,'version':'2','temporalCoverage':'2024-01-01/2025-01-01','spatialReference':{'wkid':4326}}
    docs={'catalogue':document('https://data.example.gov.au/api/3/action/package_show?id=events',catalogue),
          'old':document('https://cdn.example/dictionary-old.json',old),
          'new':document('https://cdn.example/dictionary-new.json',new)}
    contract={'source':{'dataset_url':SOURCE,'coverage':{'from':'2024-01-01','to':'2024-12-31'}},
        'resources':[{'role':'events','source_url':DATA,'grain':'crash','key':['ID'],'mapping':{
            'date':{'field':'DATE'},'geography':{'x_field':'__geometry_x','y_field':'__geometry_y','crs':'EPSG:4326'}}}]}
    accepted={claim:[{'document_id':key,'quote':'Verified caller quote'} for key in ('old','new')]
              for claim in ('grain','date','geography')}
    accepted['source_identity']=[{'document_id':'catalogue','quote':'Verified caller quote'}]
    return contract,docs,accepted


def replace(docs,key,**changes):
    value=json.loads(docs[key]['content_bytes']);value.update(changes)
    docs[key]=document(docs[key]['url'],value)


def test_dictionaries_for_distinct_periods_do_not_create_false_crs_conflict():
    contract,docs,accepted=fixture()
    result=ground_contract(contract,docs,accepted)
    assert result['ok'],result
    scope=result['applicability']['roles']['events']
    assert scope['applicable_documents']==['catalogue','new']
    assert next(d for d in scope['documents'] if d['document_id']=='old')['reasons']==['EVIDENCE_TIME_SCOPE_DISJOINT']
    assert all(e['document_id']=='new' for field in result['field_bindings'] for e in field['evidence'])
    # The same source can legitimately use the older CRS for its older records.
    contract['source']['coverage']={'from':'2018-01-01','to':'2018-12-31'}
    contract['resources'][0]['mapping']['geography']['crs']='EPSG:4283'
    older=ground_contract(contract,docs,accepted)
    assert older['ok'],older
    assert older['applicability']['roles']['events']['applicable_documents']==['catalogue','old']


def test_same_period_conflict_retains_both_documents_even_with_newer_version_and_timestamp():
    contract,docs,accepted=fixture()
    replace(docs,'old',temporalCoverage='2024-01-01/2025-01-01',dateModified='2026-01-01')
    replace(docs,'new',dateModified='2026-10-02')
    result=ground_contract(contract,docs,accepted)
    assert not result['ok']
    conflict=next(i for i in result['issues'] if i['code']=='CRS_EVIDENCE_CONFLICT')
    assert {e['document_id'] for e in conflict['evidence']}=={'old','new'}


def test_modified_date_alone_never_limits_applicability_or_resolves_conflict():
    contract,docs,accepted=fixture()
    for key in ('old','new'):
        value=json.loads(docs[key]['content_bytes']);value.pop('temporalCoverage')
        value['dateModified']='2020-01-01' if key=='old' else '2026-10-02'
        docs[key]=document(docs[key]['url'],value)
    assert any(i['code']=='CRS_EVIDENCE_CONFLICT' for i in ground_contract(contract,docs,accepted)['issues'])


def test_omitting_a_known_conflicting_citation_cannot_clear_the_conflict():
    contract,docs,accepted=fixture()
    replace(docs,'old',temporalCoverage='2024-01-01/2025-01-01')
    accepted['geography']=[{'document_id':'new','quote':'Verified current definition'}]
    result=ground_contract(contract,docs,accepted)
    assert any(i['code']=='CRS_EVIDENCE_CONFLICT' for i in result['issues'])


def test_partial_period_cannot_be_used_as_uniform_definition_for_full_upload():
    contract,docs,accepted=fixture()
    contract['source']['coverage']={'from':'2018-01-01','to':'2024-12-31'}
    result=ground_contract(contract,docs,accepted)
    assert not result['ok']
    scoped=result['applicability']['roles']['events']['documents']
    assert {item['document_id'] for item in scoped if 'EVIDENCE_TIME_SCOPE_PARTIAL' in item['reasons']}=={'old','new'}


def test_metadata_url_cannot_supply_other_resource_fields_or_omission_findings():
    from arsia_pipeline.geography_review import review_geography
    contract,docs,accepted=fixture()
    other='https://cdn.example/units.csv'
    package=json.loads(docs['catalogue']['content_bytes'])
    package['result']['resources'].append({'id':'units','url':other})
    docs['catalogue']=document(docs['catalogue']['url'],package)
    contract['resources'][0]['source_url']=other
    result=ground_contract(contract,docs,accepted)
    assert not result['ok']
    assert result['applicability']['roles']['events']['applicable_documents']==['catalogue']
    del contract['resources'][0]['mapping']['geography']
    assert review_geography(contract,docs,result,{'events':['__geometry_x','__geometry_y']})['ok']


def test_scoped_dictionary_needs_an_explicit_resource_when_dataset_has_no_matching_identity():
    contract,docs,accepted=fixture()
    del contract['resources'][0]['source_url']
    result=ground_contract(contract,docs,accepted)
    assert not result['ok']
    assert any('RESOURCE_SCOPE_REQUIRED' in row['reasons'] for row in result['applicability']['roles']['events']['documents'])


def test_invented_resource_and_model_supplied_scope_cannot_authorize():
    contract,docs,accepted=fixture()
    contract['resources'][0]['source_url']='https://other.example/forged.csv'
    contract['applicability']={'confirmed':True,'ignore_document_ids':['old']}
    result=ground_contract(contract,docs,accepted)
    assert any(i['code']=='RESOURCE_IDENTITY_UNBOUND' for i in result['issues'])


@pytest.mark.parametrize('context',["https://unknown.example/context", {'temporalCoverage':'https://evil.example/anything'}, ['https://schema.org'], {'@import':'https://schema.org'}])
def test_unknown_contexts_and_redefinitions_are_explicitly_unsupported(context):
    contract,docs,_=fixture();replace(docs,'new',**{'@context':context})
    with pytest.raises(MetadataError) as exc:build_applicability(contract,build_graph(SOURCE,docs,{'catalogue'}))
    assert exc.value.code=='JSONLD_CONTEXT_UNSUPPORTED'


@pytest.mark.parametrize('temporal',['2024/2025','2024-01-01/..','2025-01-01/2024-01-01','2024-02-30/2025-01-01'])
def test_invalid_or_unsupported_temporal_not_silently_unscoped(temporal):
    contract,docs,accepted=fixture();replace(docs,'new',temporalCoverage=temporal)
    result=ground_contract(contract,docs,accepted)
    assert not result['ok']
    assert result['issues'][0]['code'] in {'EVIDENCE_TIME_SCOPE_UNSUPPORTED','EVIDENCE_TIME_SCOPE_INVALID'}


def test_prefix_changes_preserve_scope_but_redefined_term_does_not():
    contract,docs,accepted=fixture()
    expected=ground_contract(contract,docs,accepted)['applicability']['roles']['events']['applicable_documents']
    original=json.loads(docs['new']['content_bytes'])
    changed={('@type' if key=='@type' else 's:'+key if key in ('about','version','temporalCoverage') else key):value
             for key,value in original.items() if key!='@context'}
    changed['@type']='s:DigitalDocument';changed['@context']={'s':'https://schema.org/'}
    docs['new']=document(docs['new']['url'],changed)
    assert ground_contract(contract,docs,accepted)['applicability']['roles']['events']['applicable_documents']==expected


def test_original_content_bytes_override_model_or_lossy_text_scope():
    contract,docs,accepted=fixture()
    docs['new']['text']=json.dumps({'temporalCoverage':'2010-01-01/2011-01-01'})
    assert ground_contract(contract,docs,accepted)['ok']


def test_real_receipts_enforce_scope_for_coverage_as_well_as_mapped_fields(tmp_path,monkeypatch):
    from arsia_pipeline import config
    from arsia_pipeline.trusted_qa import _proof
    from arsia_pipeline.errors import NeedsInput
    monkeypatch.setattr(config,'ROOT',tmp_path)
    contract,docs,_=fixture();contract['resources'][0]['file_id']='upload'
    (tmp_path/'sha256').mkdir()
    contract['documents']=[]
    for key,doc in docs.items():
        sha=hashlib.sha256(doc['content_bytes']).hexdigest()
        (tmp_path/'sha256'/sha).write_bytes(doc['content_bytes'])
        receipt=tmp_path/(key+'.json')
        receipt.write_text(json.dumps({'status':'fetched','sha256':sha,'final_url':doc['url'],
                                      'final_host_official':key=='catalogue'}))
        contract['documents'].append({'document_id':key,'receipt_path':str(receipt)})
    contract['evidence']={claim:[{'document_id':'new','quote':docs['new']['text']}] for claim in ('grain','date','geography','coverage_update')}
    contract['evidence']['source_identity']=[{'document_id':'catalogue','quote':docs['catalogue']['text']}]
    assert _proof(contract,tmp_path)['grounding']['applicability']['roles']['events']['applicable_documents']==['catalogue','new']
    contract['evidence']['coverage_update']=[{'document_id':'old','quote':docs['old']['text']}]
    with pytest.raises(NeedsInput) as exc:_proof(contract,tmp_path)
    assert any(i['code']=='CLAIM_APPLICABILITY_UNBOUND' for i in exc.value.details['grounding']['issues'])
