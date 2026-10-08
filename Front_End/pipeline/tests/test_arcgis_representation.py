"""Synthetic protocol fixtures; no TAS names, values or oracle in production."""
import copy
import hashlib
import json
from datetime import datetime,timezone
from urllib.parse import urlencode
import pytest
from arsia_pipeline import arcgis_query as aq
from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.evidence_grounding import ground_contract
from arsia_pipeline.metadata_extractors import MetadataError
from arsia_pipeline.issue_progress import progress_report


def fixture(layer=7,field='happened',count=3,year=2021,service='Survey/Points'):
    base='https://maps.example.gov.au/rest/services/'+service+'/FeatureServer';url=base+'/'+str(layer)
    params={'where':f"{field} >= DATE '{year}-01-01' AND {field} < DATE '{year}-02-01'",'outFields':'*','returnGeometry':'true','outSR':'4326','resultRecordCount':'20','orderByFields':'event_key','f':'geojson'}
    query=url+'/query?'+urlencode(params)
    meta={'id':layer,'objectIdField':'event_key','fields':[{'name':'event_key','type':'esriFieldTypeOID'},{'name':field,'type':'esriFieldTypeDate'}],
          'geometryType':'esriGeometryPoint','extent':{'spatialReference':{'wkid':3857}},'dateFieldsTimeReference':{'timeZoneIANA':'UTC','timeZone':'UTC'},'maxRecordCount':20}
    response={'type':'FeatureCollection','features':[{'type':'Feature','id':n,'properties':{'event_key':n,field:int(datetime(year,1,n+1,tzinfo=timezone.utc).timestamp()*1000)},'geometry':{'type':'Point','coordinates':[12.4+n/10,48.5]}} for n in range(count)]}
    return base,url,query,meta,response,field


def doc(url,value):
    raw=json.dumps(value).encode();sha=hashlib.sha256(raw).hexdigest()
    return {'url':url,'text':raw.decode(),'content_bytes':raw,'sha256':sha,'publisher_verified':True,'receipt_sha256':sha,'requested_url':url,'redirects':[]}


def bundle(tmp_path,**kw):
    base,layer,url,meta,resp,field=fixture(**kw);docs={'layer':doc(layer+'?f=pjson',meta),'query':doc(url,resp)}
    c={'source':{'dataset_url':url,'coverage':{'from':f'{kw.get("year",2021)}-01-01','to':f'{kw.get("year",2021)}-01-31'}},'update':{'mode':'incremental','from':f'{kw.get("year",2021)}-01-01','to':f'{kw.get("year",2021)}-01-31'},
       'resources':[{'role':'event','grain':'crash','file_id':'upload','source_url':url,'key':['event_key'],'mapping':{'date':{'field':field,'kind':'epoch_ms','timezone':'UTC'},'geography':{'x_field':'__geometry_x','y_field':'__geometry_y','crs':'OGC:CRS84'}}}]}
    path=tmp_path/'source.geojson';path.write_bytes(docs['query']['content_bytes']);files=[{'id':'upload','path':str(path),'sha256':docs['query']['sha256']}]
    accepted={claim:[{'document_id':'layer','quote':'legacy verified reference'}] for claim in ('source_identity','date','grain')}
    accepted['source_identity']=[{'document_id':'query','quote':'verified raw query'}]
    accepted['geography']=accepted['coverage_update']=[{'document_id':'query','quote':'verified raw query'}]
    return c,files,docs,accepted


@pytest.mark.parametrize('kwargs',[{},dict(layer=23,field='observed_on',count=8,year=2018,service='Inventory/Stations'),dict(layer=1,field='MEASURED_AT',count=1,year=2025,service='Shared/Telemetry')])
def test_protocol_variants_and_upload_binding(tmp_path,kwargs):
    c,files,docs,accepted=bundle(tmp_path,**kwargs);g=build_graph(c['source']['dataset_url'],docs,{'query'})
    r=ground_contract(c,docs,accepted,graph=g);assert r['ok'],r
    proof=aq.bind_uploads(c,files,docs,g,lambda:None)[0]
    assert proof['proofs'][0]['row_count']==kwargs.get('count',3)
    assert proof['proofs'][0]['deletion_authority'] is False
    assert r['applicability']['roles']['event']['coordinate_documents']==['query']
    assert {'query_layer_definition'}<={e['predicate'] for e in g['proof']['edges']}
    assert all(e['input_documents'][0]['sha256'] and e['rule_version'] for e in g['proof']['edges'])


@pytest.mark.parametrize('suffix',['&outSR=3857','&OUTSR=4326','&unknown=yes','&outStatistics=x','&where=1%3D1','&f=json','&returnCountOnly=true','&bad=%ZZ'])
def test_duplicate_unknown_or_conflicting_parameters_fail(suffix):
    with pytest.raises(MetadataError):aq.parse(fixture()[2]+suffix)


@pytest.mark.parametrize('key,value',[('where','event_key > 2'),('where','happened >= DATE \'2021-01-01\' OR 1=1'),('outFields','event_key,event_key'),('outFields','* AS other'),('resultOffset','20'),('resultRecordCount','0'),('outSR','3857'),('f','csv'),('orderByFields','lower(event_key)'),('where','%31=1')])
def test_supported_boundary_rejects_not_guesses(key,value):
    url=fixture()[2];from urllib.parse import parse_qsl,urlsplit
    params=dict(parse_qsl(urlsplit(url).query));params[key]=value
    with pytest.raises(MetadataError):aq.parse(url.split('?')[0]+'?'+urlencode(params))


def test_query_parameter_order_and_encoding_are_deterministic():
    url=fixture()[2];from urllib.parse import parse_qsl,urlsplit,quote
    pairs=parse_qsl(urlsplit(url).query)
    assert aq.parse(url)==aq.parse(url.split('?')[0]+'?'+urlencode(list(reversed(pairs)),quote_via=quote))


def test_other_filter_same_layer_not_same_representation(tmp_path):
    c,files,docs,_=bundle(tmp_path);c['resources'][0]['source_url']=c['source']['dataset_url'].replace('2021-01-01','2021-01-02')
    g=build_graph(c['source']['dataset_url'],docs,{'query'})
    with pytest.raises(MetadataError,match='Exact query response'):aq.bind_uploads(c,files,docs,g,lambda:None)


def test_other_layer_and_unrelated_official_document_cannot_supply_fields(tmp_path):
    c,files,docs,accepted=bundle(tmp_path);docs['layer']['url']=docs['layer']['url'].replace('/7?','/8?');v=json.loads(docs['layer']['text']);v['id']=8;docs['layer']=doc(docs['layer']['url'],v)
    g=build_graph(c['source']['dataset_url'],docs,{'query'});assert 'layer' not in g['authorized'];assert not ground_contract(c,docs,accepted,graph=g)['ok']


def test_forged_layer_id_fails(tmp_path):
    c,files,docs,_=bundle(tmp_path);v=json.loads(docs['layer']['text']);v['id']=77;docs['layer']=doc(docs['layer']['url'],v)
    with pytest.raises(MetadataError,match='different layers'):build_graph(c['source']['dataset_url'],docs,{'query'})


def test_service_requires_explicit_membership():
    base,layer,url,meta,resp,_=fixture()
    docs={'service':doc(base,{'layers':[{'id':7}]}),'layer':doc(layer,meta),'query':doc(url,resp)}
    assert build_graph(base,docs,{'service'})['authorized']==set(docs)
    docs['service']=doc(base,{'layers':[{'id':9}]})
    assert build_graph(base,docs,{'service'})['authorized']=={'service'}


@pytest.mark.parametrize('mutation,code',[
    (lambda m,r:r.update(exceededTransferLimit=True),'TRUNCATED'),
    (lambda m,r:r['features'].append(copy.deepcopy(r['features'][0])),'OBJECT_ID_CONFLICT'),
    (lambda m,r:r['features'][0]['properties'].pop('happened'),'FIELD_CONFLICT'),
    (lambda m,r:r.update(crs={'type':'name','properties':{'name':'EPSG:3857'}}),'OUTPUT_CRS_CONFLICT'),
    (lambda m,r:r['features'][0]['properties'].update(happened=0),'RANGE_CONFLICT'),
    (lambda m,r:m.update(datesInUnknownTimezone=True),'TIME_UNSUPPORTED'),
    (lambda m,r:m.update(dateFieldsTimeReference={'timeZone':'invented'}),'TIME_UNSUPPORTED'),
    (lambda m,r:m['fields'][1].update(type='esriFieldTypeDateOnly'),'TIME_UNSUPPORTED'),
    (lambda m,r:m.update(timeInfo={'startTimeField':'happened'}),'TIME_UNSUPPORTED')])
def test_response_and_derivation_negatives(mutation,code):
    _,_,url,meta,response,_=fixture();mutation(meta,response)
    with pytest.raises(MetadataError) as ex:aq.verify_response(aq.parse(url),meta,response)
    assert code in ex.value.code


def test_at_limit_without_end_marker_is_ambiguous():
    _,_,url,meta,response,_=fixture(count=20)
    with pytest.raises(MetadataError):aq.verify_response(aq.parse(url),meta,response)
    response['exceededTransferLimit']=False
    assert aq.verify_response(aq.parse(url),meta,response)['row_count']==20


@pytest.mark.parametrize('mutation,code',[
    (lambda c,f,d:f[0].update(sha256='f'*64),'HASH_CONFLICT'),
    (lambda c,f,d:c['resources'][0]['mapping']['date'].update(timezone='Etc/GMT-10'),'TIMEZONE_CONFLICT'),
    (lambda c,f,d:c['resources'][0]['mapping']['date'].update(kind='epoch_s'),'DATE_MAPPING_CONFLICT'),
    (lambda c,f,d:c['update'].update(mode='unknown'),'UPDATE_UNSUPPORTED'),
    (lambda c,f,d:c['update'].update(to='2021-02-02'),'UPDATE_RANGE_CONFLICT')])
def test_host_binding_and_safe_update(tmp_path,mutation,code):
    c,f,d,_=bundle(tmp_path);mutation(c,f,d);g=build_graph(c['source']['dataset_url'],d,{'query'})
    with pytest.raises(MetadataError) as ex:aq.bind_uploads(c,f,d,g,lambda:None)
    assert code in ex.value.code


def test_same_structure_different_upload_bytes_is_not_provenance(tmp_path):
    c,f,d,_=bundle(tmp_path);path=__import__('pathlib').Path(f[0]['path'])
    value=json.loads(path.read_bytes());value['features'][0]['properties']['event_key']=999
    path.write_text(json.dumps(value));f[0]['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(MetadataError,match='not a complete lossless representation'):aq.bind_uploads(c,f,d,build_graph(c['source']['dataset_url'],d,{'query'}),lambda:None)


def test_count_disagreement_stops_without_refetch(tmp_path):
    c,f,d,_=bundle(tmp_path);url=c['source']['dataset_url'];p=aq.parse(url);d['count']=doc(p['layer']+'/query?'+urlencode({'where':p['parameters']['where'],'returnCountOnly':'true','f':'json'}),{'count':4})
    with pytest.raises(MetadataError,match='Official count disagrees'):aq.bind_uploads(c,f,d,build_graph(url,d,{'query'}),lambda:None)
    d['count']=doc(d['count']['url'],{'count':3});out=aq.bind_uploads(c,f,d,build_graph(url,d,{'query'}),lambda:None)
    assert out[0]['proofs'][0]['count_cross_checks'][0]['count']==3 and not out[0]['proofs'][0]['deletion_authority']


def test_cancel_is_propagated(tmp_path):
    from arsia_pipeline.errors import ImportCancelled
    c,f,d,_=bundle(tmp_path)
    def cancel():raise ImportCancelled()
    with pytest.raises(ImportCancelled):aq.bind_uploads(c,f,d,build_graph(c['source']['dataset_url'],d,{'query'}),cancel)


def test_check_early_exit_partial_pass_and_repeated_proof():
    from test_issue_progress import step,SETTINGS,issue
    x=issue('MAPPED_FIELD_UNGROUNDED',field='x');y=issue('MAPPED_FIELD_UNGROUNDED',field='y')
    events=[step(1,'preflight_contract',{'ok':False,'blockers':[x,y]})]
    events.append(step(2,'preflight_contract',{'ok':False,'blockers':[y],'checks':[{**x,'status':'not_checked'}]}))
    assert len(progress_report(events,SETTINGS)['unresolved_issues'])==2
    events.append(step(3,'preflight_contract',{'ok':False,'blockers':[y],'checks':[{**x,'status':'pass'}]}))
    r=progress_report(events,SETTINGS);assert len(r['unresolved_issues'])==1 and r['last_progress_step_id']==3
    events += [step(n,'preflight_contract',{'ok':False,'blockers':[y],'checks':[{**x,'status':'pass'}]}) for n in range(4,10)]
    r=progress_report(events,SETTINGS);assert r['state']=='stalled' and r['last_progress_step_id']==3


def test_identity_does_not_erase_representation_scope():
    from arsia_pipeline.source_identity import url_identity
    _,layer,url,_,_,_=fixture()
    other=url.replace('2021-01-01','2021-01-02')
    assert url_identity(url)==url_identity(layer)==url_identity(other)
    assert aq.parse(url)!=aq.parse(other)
    assert url_identity(url+'&unknown=1') is None


@pytest.mark.parametrize('error,expected',[('cancel','cancelled'),('system','needs_input'),('budget','needs_input')])
def test_relay_completion_cannot_revive_terminal(tmp_path,monkeypatch,error,expected):
    import io,threading
    from types import SimpleNamespace
    from arsia_pipeline import codex_bridge
    from arsia_pipeline.errors import ImportCancelled,NeedsInput,BudgetExhausted
    bridge=codex_bridge.TaskBridge.__new__(codex_bridge.TaskBridge)
    states=[];s=SimpleNamespace(ready=False,usage={'model_calls':0},agent_policy={},status='investigating',check_budget=lambda **kw:None,step=lambda *a:1,finish_step=lambda *a:None)
    def persist(status='investigating'):s.status=status;states.append(status)
    s.persist=persist;bridge.session=s;bridge.workspace=tmp_path/'task';bridge.workspace.mkdir();bridge.lock=threading.RLock();bridge.closed=threading.Event();bridge.terminal=None;bridge.model_active=False;bridge.connections=set()
    terminal={'cancel':ImportCancelled(),'system':NeedsInput('system',[]),'budget':BudgetExhausted('budget')}[error]
    class Connection:
        def __init__(self,*a,**kw):pass
        def request(self,*a,**kw):pass
        def close(self):pass
        def getresponse(self):return SimpleNamespace(status=200,read=self.read)
        def read(self,*a):
            bridge.terminal=terminal
            return b'{"object":"response.compaction","usage":{}}'
    s.id='0c846645-e379-4551-9c16-d102e566227f'
    monkeypatch.setattr(codex_bridge,'read_config',lambda:{'agent_gateway_token':'synthetic',
        'instance_id':'b617146e5426478b8e0c2f73f31b046c'})
    monkeypatch.setattr(codex_bridge.http.client,'HTTPConnection',Connection)
    handler=SimpleNamespace(path='/v1/responses/compact',send_response=lambda *a:None,send_header=lambda *a:None,end_headers=lambda:None,wfile=io.BytesIO())
    bridge.relay(handler,{'model':'gpt-6.1-sol'})
    assert states[-1]==expected and not bridge.model_active
    with pytest.raises(ValueError,match='Task stopped'):bridge.relay(handler,{'model':'gpt-6.1-sol'})


@pytest.mark.parametrize('mode',['snapshot','partition','incremental'])
def test_bounded_representation_allows_observed_analysis_but_grants_no_deletion(tmp_path,mode):
    c,files,docs,_=bundle(tmp_path);c['update']['mode']=mode
    proof=aq.bind_uploads(c,files,docs,build_graph(c['source']['dataset_url'],docs,{'query'}),lambda:None)
    assert proof[0]['proofs'][0]['row_count']==3
    assert proof[0]['proofs'][0]['completeness']=='bounded_response_only'
    assert proof[0]['proofs'][0]['deletion_authority'] is False
