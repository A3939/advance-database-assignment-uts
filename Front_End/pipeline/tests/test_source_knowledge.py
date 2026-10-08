import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from arsia_pipeline import source_knowledge as kb, adapter_reuse as reuse


def file(path, data=b'ID,DATE\n001,2024-01-01\n', ident='one'):
    path.write_bytes(data)
    return {'id':ident,'name':path.name,'path':str(path),'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}


def cache_fixture(tmp_path, monkeypatch):
    f=file(tmp_path/'source.csv')
    contract={'contract_version':'canonical-v2','source':{'source_id':'fixture'},
              'resources':[{'role':'crash','file_id':'one','grain':'crash','key':['ID']}], 'evidence':{}}
    from arsia_pipeline.registry import execution_contract_hash
    admission={'status':'admitted','source_contract_sha256':execution_contract_hash(contract),'image':'sha256:fixture'}
    normalized=copy.deepcopy(contract);normalized['resources'][0].pop('file_id')
    record={'contract':normalized,'code_sha256':hashlib.sha256(reuse.ADAPTER.encode()).hexdigest(),
            'verification':{'admission':admission}}
    monkeypatch.setattr(reuse,'registered',lambda _:record)
    session=SimpleNamespace(validated={'admission':admission,'source_contract':contract},registered={'adapter_version_id':'v1'},
                            code=reuse.ADAPTER,files=[f],documents={})
    cache=reuse.ReuseCache(tmp_path/'cache','instance-a')
    cache.remember(session)
    return cache,session,f,record


def test_all_jurisdictions_and_grains_are_explicit():
    catalog=kb.load_catalog()
    assert {j for s in catalog['sources'] for j in s['jurisdiction']}=={'NSW','VIC','QLD','SA','WA','TAS','ACT','NT','AU'}
    assert len(catalog['sources'])==13
    qld=next(s for s in catalog['sources'] if s['id']=='qld-crash-data')
    assert next(r for r in qld['resources'] if r['name']=='Road casualties')['grain']=='observation'
    assert not any(s.get('admitted') for s in catalog['sources'])


def test_every_packaged_receipt_hash_and_scoped_resource_reference():
    catalog=kb.load_catalog();store=kb.EvidenceStore(kb.CATALOG.parent/'evidence')
    for key,entry in catalog['evidence_index'].items():
        if entry['status']=='fetched':assert len(store.get(entry['sha256']))==entry['size']
    for source in catalog['sources']:
        assert all(e in catalog['evidence_index'] for e in source['evidence'])
        for r in source['resources']:
            if r.get('evidence'):assert r['evidence']['id'] in catalog['evidence_index']


def test_compact_lookup_then_targeted_dictionary():
    listing=kb.lookup();assert len(json.dumps(listing))<7000
    assert all('resources' not in s for s in listing['sources'])
    resource=kb.lookup(dataset_id='qld-crash-data',resource_id='e88943c0-5968-4972-a15f-38e120d72ec0')['sources'][0]['resources'][0]
    assert resource['headers'][0]=='Crash_Ref_Number'
    evidence=kb.read_evidence('qld-sample',locator='/result/fields/10')
    assert evidence['admission_authority'] is False
    assert 'GDA2020' in evidence['text']


def test_pdf_page_locator_and_access_failure():
    assert '8059' in kb.read_evidence('sa-dictionary',locator='page:2')['text']
    assert not kb.read_evidence('bitre')['available']
    with pytest.raises(ValueError):kb.read_evidence('sa-dictionary',locator='../secret')


def test_content_dedup_and_corruption(tmp_path):
    store=kb.EvidenceStore(tmp_path/'objects');sha=store.put(b'evidence')
    assert store.put(b'evidence')==sha and len(list(store.root.iterdir()))==1
    (store.root/sha).chmod(0o600);(store.root/sha).write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):store.get(sha)
    with pytest.raises(ValueError):store.get('../secret')


def test_symlink_store_rejected(tmp_path):
    (tmp_path/'real').mkdir();(tmp_path/'alias').symlink_to(tmp_path/'real')
    with pytest.raises(ValueError):kb.EvidenceStore(tmp_path/'alias'/'nested')


@pytest.mark.parametrize('headers',[['ID','ID'],[' ID','ID'],['ＩＤ','ID'],['id','ID'],['','ID']])
def test_ambiguous_columns_never_normalize_away(headers):
    with pytest.raises(ValueError):kb.schema_signature(headers)


def test_column_order_invariant_but_rename_is_drift():
    assert kb.schema_signature(['ID','DATE'])==kb.schema_signature(['DATE','ID'])
    assert kb.schema_delta(['ID','DATE'],['DATE','ID'])=={'added':[],'removed':[],'order_changed':True}
    assert kb.schema_delta(['ID','DATE'],['ID','Date'])['removed']==['DATE']


def test_metadata_delta_selects_related_evidence_not_whole_source():
    old={'resources':{'r1':{'crs':'GDA94'},'r2':{'crs':'WGS84'}}};new=copy.deepcopy(old);new['resources']['r1']['crs']='GDA2020'
    claims=[{'id':'coordinate-r1','depends_on':['/resources/r1/crs'],'evidence_ids':['qld-sample']},
            {'id':'coordinate-r2','depends_on':['/resources/r2/crs'],'evidence_ids':['other']}]
    delta=kb.semantic_diff(old,new,claims)
    assert len(delta['changes'])==1
    assert delta['changes'][0]['evidence_ids']==['qld-sample']
    assert not delta['admitted']


def test_diff_preserves_axis_order_and_bounds_context():
    assert kb.semantic_diff({'axes':['x','y']},{'axes':['y','x']})['changes']
    delta=kb.semantic_diff({}, {str(i):'x'*5000 for i in range(100)})
    assert delta['truncated'] and len(delta['changes'])==80
    assert delta['changes'][0]['after']['omitted']


def test_ckan_projection_ignores_only_known_cosmetics():
    raw={'result':{'id':'a','resources':[{'id':'one','url':'https://source.gov.au/x'}], 'notes':'GDA94','tracking_summary':{'total':1}}}
    newer=copy.deepcopy(raw);newer['result']['tracking_summary']['total']=200
    assert kb.metadata_projection(raw,'ckan')==kb.metadata_projection(newer,'ckan')
    newer['result']['notes']='GDA2020'
    assert kb.semantic_diff(kb.metadata_projection(raw,'ckan'),kb.metadata_projection(newer,'ckan'))['changes']
    with pytest.raises(ValueError):kb.metadata_projection({'error':{'code':500}},'arcgis')


def test_filename_is_never_source_authority(tmp_path):
    f=file(tmp_path/'ACT_Road_Crash_Data.csv')
    result=kb.inspect_files([f]);assert result['route']=='autonomous_investigation' and not result['admitted']


def test_actual_act_header_candidate_remains_research_only_with_current_runtime_status(tmp_path):
    source=kb.lookup(dataset_id='act-road-crash',resource_id='6jn4-m8rx')['sources'][0]
    headers=source['resources'][0]['headers']
    f=file(tmp_path/'renamed.csv',(','.join(headers)+'\n').encode())
    result=kb.inspect_files([f]);candidate=result['tables'][0]['candidates'][0]
    assert candidate['dataset_id']=='act-road-crash' and candidate['adapter_status']=='research_only_current_input_requires_fresh_QA'
    assert not result['admitted']


def test_exact_renamed_upload_rebinds_ids_but_does_not_admit(tmp_path,monkeypatch):
    cache,session,f,_=cache_fixture(tmp_path,monkeypatch)
    new=file(tmp_path/'renamed.csv',Path(f['path']).read_bytes(),'new-id')
    candidate,decision=cache.match([new])
    assert candidate['contract']['resources'][0]['file_id']=='new-id'
    assert decision['route']=='verified_recipe_requires_fresh_QA'
    assert session.validated['source_contract']['resources'][0]['file_id']=='one'


def test_changed_data_extra_uploads_and_duplicates_never_reuse(tmp_path,monkeypatch):
    cache,_,f,_=cache_fixture(tmp_path,monkeypatch)
    changed=file(tmp_path/'changed.csv',b'ID,DATE\n001,2024-02-01\n','new')
    duplicate=file(tmp_path/'duplicate.csv',Path(f['path']).read_bytes(),'dup')
    for files in ([changed],[f,changed],[f,duplicate]):assert cache.match(files)[0] is None


def test_dependency_change_invalidates(tmp_path,monkeypatch):
    cache,_,f,_=cache_fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(reuse,'dependencies',lambda:{'policy':'new'})
    candidate,decision=cache.match([f]);assert candidate is None
    assert decision['invalidations'][0]['reason']=='dependency_changed'


def test_registry_remains_authority(tmp_path,monkeypatch):
    cache,_,f,record=cache_fixture(tmp_path,monkeypatch)
    record['contract']['source']['source_id']='another'
    with pytest.raises(ValueError,match='immutable'):cache.match([f])


def test_cache_instance_isolation_and_reject_sample_promotion(tmp_path,monkeypatch):
    cache,session,f,_=cache_fixture(tmp_path,monkeypatch)
    assert reuse.ReuseCache(tmp_path/'cache','instance-b').match([f])[0] is None
    session.validated['admission']['status']='sample_only'
    with pytest.raises(ValueError):cache.remember(session)


def test_disabled_integration_has_no_calls():
    session=SimpleNamespace(native_context=None)
    assert reuse.prepare(session,{}) is None


def test_codex_specs_include_bounded_knowledge_tools():
    from arsia_pipeline.codex_bridge import SPECS
    assert 'read_source_knowledge' in SPECS and 'read_source_evidence' in SPECS
    assert SPECS['read_source_evidence']['parameters']['properties']['max_chars']['maximum']==16000
    assert 'compare_source_metadata' in SPECS


def test_match_does_not_skip_independent_candidate_QA(tmp_path):
    from test_canonical_v2 import envelope
    from arsia_pipeline.trusted_qa import validate_candidate
    from arsia_pipeline.errors import ValidationFailure
    contract,f,run=envelope(tmp_path,lambda row:row.update(fatalities=999))
    with pytest.raises(ValidationFailure,match='independent'):
        validate_candidate(run,contract,[f],'code-sha',tmp_path)


def test_concurrent_content_writers_publish_one_complete_object(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store=kb.EvidenceStore(tmp_path/'objects');data=b'x'*100000
    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes=list(pool.map(lambda _:store.put(data),range(32)))
    assert len(set(hashes))==1 and store.get(hashes[0])==data
    assert len(list(store.root.iterdir()))==1


def test_known_metadata_change_uses_registered_bytes_and_scoped_diff(tmp_path):
    entry=kb.load_catalog()['evidence_index']['qld']
    value=json.loads(kb.EvidenceStore(kb.CATALOG.parent/'evidence').get(entry['sha256']))
    value['result']['notes']='Changed coordinate datum requires investigation'
    folder=tmp_path/'public';objects=kb.EvidenceStore(folder/'sha256')
    sha=objects.put(json.dumps(value).encode());receipt=folder/'receipt.json'
    receipt.write_text(json.dumps({'status':'fetched','sha256':sha,'final_url':entry['final_url']}))
    doc={'document_id':'fresh','sha256':sha,'receipt_path':str(receipt)}
    delta=kb.compare_registered_metadata('qld',doc,'ckan',tmp_path)
    assert delta['route']=='delta_investigation' and len(delta['changes'])==1
    assert delta['changes'][0]['path']=='/notes'
    assert delta['changes'][0]['evidence_ids']==['fresh','qld']
    with pytest.raises(ValueError):kb.compare_registered_metadata('qld',doc,'ckan',tmp_path/'unrelated')
    (objects.root/sha).chmod(0o600);(objects.root/sha).write_text('{}')
    with pytest.raises(ValueError,match='changed'):kb.compare_registered_metadata('qld',doc,'ckan',tmp_path)


def test_receipt_identity_change_never_assumes_same_dataset(tmp_path):
    entry=kb.load_catalog()['evidence_index']['act']
    value=json.loads(kb.EvidenceStore(kb.CATALOG.parent/'evidence').get(entry['sha256']));value['id']='other-dataset'
    objects=kb.EvidenceStore(tmp_path/'sha256');sha=objects.put(json.dumps(value).encode())
    receipt=tmp_path/'receipt.json';receipt.write_text(json.dumps({'status':'fetched','sha256':sha}))
    delta=kb.compare_registered_metadata('act',{'sha256':sha,'document_id':'new','receipt_path':str(receipt)},'socrata',tmp_path)
    assert delta['route']=='source_identity_review' and not delta['admitted']


def test_changed_pinned_evidence_invalidates_recipe(tmp_path,monkeypatch):
    _,session,f,_=cache_fixture(tmp_path,monkeypatch)
    text=tmp_path/'metadata.txt';text.write_text('source evidence')
    session.documents={'doc':{'document_id':'doc','text_path':str(text)}}
    cache=reuse.ReuseCache(tmp_path/'new-cache','instance-a');cache.remember(session)
    text.write_text('changed source evidence')
    candidate,decision=cache.match([f]);assert candidate is None
    assert decision['invalidations'][0]['reason']=='evidence_changed'


def test_non_utf8_unknown_can_continue_autonomous_encoding_investigation(tmp_path):
    f=file(tmp_path/'legacy.csv',b'ID,PLACE\n001,\xff\xfe\xff\n')
    result=kb.inspect_files([f])
    assert result['route']=='autonomous_investigation' and result['tables'][0]['requires_inspection']


def test_new_uploaded_dictionary_prevents_silent_reuse(tmp_path,monkeypatch):
    cache,_,f,_=cache_fixture(tmp_path,monkeypatch)
    pdf=file(tmp_path/'new-dictionary.pdf',b'%PDF-1.4\nNew source definitions',ident='dictionary')
    candidate,decision=cache.match([f,pdf])
    assert candidate is None
    assert decision['invalidations'][0]['reason']=='supporting_documents_changed'
