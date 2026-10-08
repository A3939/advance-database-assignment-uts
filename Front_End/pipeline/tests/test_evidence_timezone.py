"""Independent expectations for scoped research and pinned date semantics."""
import copy,hashlib,json,shutil
from datetime import datetime,timezone
import pytest
from arsia_pipeline import timezone_rules as tz
from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.metadata_extractors import MetadataError
from arsia_pipeline.arcgis_query import bind_uploads
from arsia_pipeline.trusted_qa import semantic_contract
from test_arcgis_representation import bundle,doc
from test_evidence_graph import SOURCE,CDN,catalog

UNSAFE='<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///etc/passwd">]><x>&leak;</x>'
def research():return {'url':'https://standards.example/research.xml','content_bytes':UNSAFE.encode(),'text':UNSAFE,'role':'research'}

def test_E01_E07_unrelated_error_is_audited_not_authority_or_identity(tmp_path):
 c,f,d,a=bundle(tmp_path);before=build_graph(c['source']['dataset_url'],d,{'query'})
 d['research']=research();after=build_graph(c['source']['dataset_url'],d,{'query'})
 assert before['proof']==after['proof'];assert 'research' not in after['authorized']
 row=next(x for x in after['selection']['documents'] if x['document_id']=='research')
 assert row['error']['code']=='METADATA_UNSAFE_XML' and not row['selected'] and not row['blocking']
 assert after==build_graph(c['source']['dataset_url'],dict(reversed(list(d.items()))),{'query'})
 assert bind_uploads(c,f,d,after,lambda:None)[0]['proofs'][0]['row_count']==3
 old=semantic_contract(c);c['documents']=[{'document_id':'research','url':research()['url']}]
 assert old==semantic_contract(c)

@pytest.mark.parametrize('mode',['cited','official_same_resource','delegated'])
def test_E02_E03_E04_relevant_parse_error_blocks(mode,tmp_path):
 c,f,d,a=bundle(tmp_path);source=c['source']['dataset_url'];cited={'query'};extra=set()
 d['bad']=research()
 if mode=='cited':extra={'bad'}
 if mode=='official_same_resource':d['bad']['url']=d['layer']['url'];d['bad']['publisher_verified']=True
 if mode=='delegated':source=SOURCE;d={'catalogue':catalog(),'bad':research()};d['bad']['url']=CDN;cited={'catalogue'}
 with pytest.raises(MetadataError) as e:build_graph(source,d,cited,cited_ids=extra)
 assert e.value.code=='METADATA_UNSAFE_XML';assert e.value.details['document_id']=='bad'
 assert next(x for x in e.value.details['selection']['documents'] if x['document_id']=='bad')['blocking']

def test_E03_uncited_official_conflict_not_hidden_by_research(tmp_path):
 c,f,d,a=bundle(tmp_path);m=json.loads(d['layer']['text']);m['id']=999
 d['conflict']=doc(d['layer']['url'],m);d['conflict']['role']='research'
 with pytest.raises(MetadataError) as e:build_graph(c['source']['dataset_url'],d,{'query'})
 assert e.value.code=='SOURCE_METADATA_ID_CONFLICT'

@pytest.mark.parametrize('exc',[TimeoutError('deadline'),MemoryError('limit'),RuntimeError('bug')])
def test_E08_system_errors_propagate(monkeypatch,tmp_path,exc):
 c,f,d,a=bundle(tmp_path)
 def stop(*a,**kw):raise exc
 monkeypatch.setattr('arsia_pipeline.evidence_graph.extract',stop)
 with pytest.raises(type(exc)):build_graph(c['source']['dataset_url'],d,{'query'})

def test_E08_cancel_propagates(tmp_path):
 c,f,d,a=bundle(tmp_path)
 from arsia_pipeline.errors import ImportCancelled
 def stop():raise ImportCancelled()
 with pytest.raises(ImportCancelled):build_graph(c['source']['dataset_url'],d,{'query'},check_cancelled=stop)

def ref(**kw):return {'dateFieldsTimeReference':kw,'fields':[{'name':'event_time','type':'esriFieldTypeDate'}]}
def resolve(m,interval=None):return tz.resolve_time_reference(m,'event_time','MapServer',interval)
@pytest.mark.parametrize('name,expected',[('India Standard Time','Asia/Kolkata'),('Nepal Standard Time','Asia/Kathmandu'),('Eastern Standard Time','America/New_York'),('Cen. Australia Standard Time','Australia/Adelaide'),('W. Australia Standard Time','Australia/Perth'),('Chatham Islands Standard Time','Pacific/Chatham')])
def test_T01_windows_defaults(name,expected):
 assert resolve(ref(timeZone=name,respectsDaylightSaving=True))['iana']==expected

@pytest.mark.parametrize('name,expected',[('UTC','UTC'),('Etc/UTC','UTC'),('US/Eastern','America/New_York'),('Asia/Calcutta','Asia/Kolkata')])
def test_T02_aliases(name,expected):assert resolve(ref(timeZoneIANA=name))['iana']==expected
@pytest.mark.parametrize('m',[ref(timeZone='unknown'),ref(timeZoneIANA='Unknown'),ref(timeZoneIANA='../UTC'),ref(timeZoneIANA='UTC',timeZone='Eastern Standard Time'),ref(timeZoneIANA='Australia/Brisbane',timeZone='AUS Eastern Standard Time'),ref(timeZoneIANA=None,timeZone='UTC'),ref(timeZoneIANA='UTC',respectsDaylightSaving=None),ref(timeZoneIANA='UTC',respectsDaylightSaving='false')])
def test_T02_invalid_conflicting(m):
 with pytest.raises(tz.TimeReferenceError):resolve(m)

@pytest.mark.parametrize('kind',['MapServer','FeatureServer'])
def test_T02_protocol_default_distinct_from_unknown(kind):
 for m in ({},{'dateFieldsTimeReference':None}):assert tz.resolve_time_reference(m,'field',kind)['iana']=='UTC'
 for m in ({'datesInUnknownTimezone':True},{'datesInUnknownTimezone':'false'},ref(timeZone='Unknown')):
  with pytest.raises(tz.TimeReferenceError):tz.resolve_time_reference(m,'field',kind)

@pytest.mark.parametrize('name,start,end,passed',[('W. Australia Standard Time','2023-01-01','2023-02-01',True),('W. Australia Standard Time','2008-01-01','2008-02-01',False),('Eastern Standard Time','2023-01-01','2024-01-01',False),('India Standard Time','2023-01-01','2024-01-01',True)])
def test_T03_full_interval_no_dst(name,start,end,passed):
 m=ref(timeZone=name,respectsDaylightSaving=False);interval={'from':start,'until_exclusive':end}
 if passed:assert resolve(m,interval)['dst_proof']['no_dst_equivalent']
 else:
  with pytest.raises(tz.TimeReferenceError):resolve(m,interval)

@pytest.mark.parametrize('text',['2023-03-12T02:30:00','2023-11-05T01:30:00'])
def test_T03_ambiguous_nonexistent_boundary(text):
 with pytest.raises(tz.TimeReferenceError,match='Ambiguous or nonexistent'):tz._boundary(text,tz.pinned_zone('America/New_York'))

@pytest.mark.parametrize('utc,zone,expected',[('2023-01-31T18:30:00','Asia/Kolkata','2023-02-01'),('2023-03-12T04:59:00','America/New_York','2023-03-11'),('2023-03-12T07:01:00','America/New_York','2023-03-12'),('2023-11-05T05:30:00','America/New_York','2023-11-05'),('2023-11-05T06:30:00','America/New_York','2023-11-05')])
def test_T04_epoch_date_independent_expected(utc,zone,expected):
 # Use the same shared conversion consumed by real generated adapters.
 from arsia_pipeline.canonical import date_value
 epoch=int(datetime.fromisoformat(utc).replace(tzinfo=timezone.utc).timestamp()*1000)
 assert date_value({'when':epoch},{'field':'when','kind':'epoch_ms','timezone':zone},{})['occurrence_date']==expected

@pytest.mark.parametrize('change',[lambda m:m.update(timeInfo={'startTimeField':'event_time'}),lambda m:m.update(editFieldsInfo={'editDateField':'event_time'}),lambda m:m['fields'][0].update(type='esriFieldTypeDateOnly'),lambda m:m['fields'][0].update(type='esriFieldTypeTimestampOffset')])
def test_T05_unsupported_field_semantics(change):
 m=ref(timeZone='UTC');change(m)
 with pytest.raises(tz.TimeReferenceError):resolve(m)

@pytest.mark.parametrize('mutation',['missing','corrupt','version'])
def test_T06_no_fallback_on_rule_change(tmp_path,monkeypatch,mutation):
 from arsia_pipeline.trusted_qa import trusted_implementation
 original=trusted_implementation()
 assert 'knowledge/timezones/tzdb.zip' in original and 'timezone_rules.py' in original
 shutil.copytree(tz.RULES,tmp_path/'rules');target=tmp_path/'rules'
 if mutation=='missing':(target/'tzdb.zip').unlink()
 elif mutation=='corrupt':(target/'windowsZones.json').write_bytes(b'{}')
 else:
  v=json.loads((target/'manifest.json').read_text());v['tzdb_version']='other';(target/'manifest.json').write_text(json.dumps(v))
 monkeypatch.setattr(tz,'RULES',target);tz.bundle.cache_clear();tz.pinned_zone.cache_clear()
 try:
  with pytest.raises(tz.TimeReferenceError) as e:resolve(ref(timeZone='UTC'))
  assert e.value.code=='TIMEZONE_RULE_INTEGRITY'
 finally:tz.bundle.cache_clear();tz.pinned_zone.cache_clear()

def test_X01_combined_synthetic_official_upload(tmp_path):
 c,f,d,a=bundle(tmp_path,layer=19,field='occurred_at',count=5,year=2019,service='Roads/Alternate')
 m=json.loads(d['layer']['text']);m['dateFieldsTimeReference']={'timeZone':'Nepal Standard Time','respectsDaylightSaving':False}
 d['layer']=doc(d['layer']['url'],m);d['research']=research()
 c['resources'][0]['mapping']['date']['timezone']='Asia/Kathmandu'
 g=build_graph(c['source']['dataset_url'],d,{'query'})
 proof=bind_uploads(c,f,d,g,lambda:None)[0]['proofs'][0]
 assert proof['row_count']==5 and proof['time_reference_proof']['iana']=='Asia/Kathmandu'
 c['resources'][0]['mapping']['date']['timezone']='America/New_York'
 with pytest.raises(MetadataError) as e:bind_uploads(c,f,d,g,lambda:None)
 assert e.value.code=='ARCGIS_TIMEZONE_CONFLICT'

def test_aliases_preserve_semantic_identity():
 c={'resources':[{'role':'event','file_id':'a','mapping':{'date':{'field':'when','kind':'epoch_ms','timezone':'US/Eastern'}}}]}
 a=semantic_contract(c);c['resources'][0]['mapping']['date']['timezone']='America/New_York'
 assert a==semantic_contract(c)
 c['resources'][0]['mapping']['date']['timezone']='UTC';assert a!=semantic_contract(c)

@pytest.mark.parametrize('utc,valid',[('2018-12-31T18:15:00',True),('2018-12-31T18:14:59',False),('2019-01-31T18:14:59',True),('2019-01-31T18:15:00',False)])
def test_T04_local_half_open_boundaries(utc,valid):
 from test_arcgis_representation import fixture
 from arsia_pipeline.arcgis_query import parse,verify_response
 _,_,url,meta,response,field=fixture(layer=19,field='occurred_at',count=1,year=2019)
 meta['dateFieldsTimeReference']={'timeZone':'Nepal Standard Time','respectsDaylightSaving':False}
 response['features'][0]['properties'][field]=int(datetime.fromisoformat(utc).replace(tzinfo=timezone.utc).timestamp()*1000)
 if valid:assert verify_response(parse(url),meta,response)['row_count']==1
 else:
  with pytest.raises(MetadataError) as e:verify_response(parse(url),meta,response)
  assert e.value.code=='ARCGIS_RANGE_CONFLICT'

@pytest.mark.parametrize('raw',[b'{broken',b'<r>'+b'<a>'*100+b'</a>'*100+b'</r>'])
def test_E08_bad_json_and_deep_xml_are_not_silently_parsed(tmp_path,raw):
 c,f,d,a=bundle(tmp_path);d['bad']={'url':'https://research.example/definition','content_bytes':raw}
 graph=build_graph(c['source']['dataset_url'],d,{'query'})
 row=next(x for x in graph['selection']['documents'] if x['document_id']=='bad')
 assert row['parse_status']=='error' and not row['blocking']
 with pytest.raises(MetadataError):build_graph(c['source']['dataset_url'],d,{'query'},cited_ids={'bad'})

@pytest.mark.parametrize('windows,iana,offset',[
 ('Tasmania Standard Time','Etc/GMT-10',10),
 ('Eastern Standard Time','Etc/GMT+5',-5),
])
def test_explicit_fixed_iana_agrees_with_declared_windows_standard_time(windows,iana,offset):
 interval={'from':'2024-01-01','until_exclusive':'2025-01-01'}
 value=resolve(ref(timeZone=windows,timeZoneIANA=iana,respectsDaylightSaving=False),interval)
 assert value['iana']==iana and value['dst_proof']['standard_time_equivalent'] is True
 # An independent fixed-offset clock includes summer, winter and date rollover.
 from datetime import timedelta
 for month in (1,4,7,10):
  instant=datetime(2024,month,1,18,30,tzinfo=timezone.utc)
  assert instant.astimezone(tz.pinned_zone(value['iana'])).date()==(instant+timedelta(hours=offset)).date()

@pytest.mark.parametrize('change',[
 {'timeZoneIANA':'Etc/GMT-11'}, {'timeZoneIANA':'Etc/GMT-9'},
 {'respectsDaylightSaving':True}, {'timeZoneIANA':'Australia/Hobart'},
])
def test_dual_no_dst_timezone_actual_conflicts_still_rejected(change):
 value={'timeZone':'Tasmania Standard Time','timeZoneIANA':'Etc/GMT-10','respectsDaylightSaving':False};value.update(change)
 with pytest.raises(tz.TimeReferenceError):resolve(ref(**value),{'from':'2024-01-01','until_exclusive':'2025-01-01'})

def test_no_dst_dual_proof_is_bounded_and_historical_base_changes_not_hidden():
 value=ref(timeZone='Tasmania Standard Time',timeZoneIANA='Etc/GMT-10',respectsDaylightSaving=False)
 with pytest.raises(tz.TimeReferenceError):resolve(value)
 with pytest.raises(tz.TimeReferenceError):resolve(value,{'from':'1800-01-01','until_exclusive':'1900-01-01'})
