"""Complete typed-JSON equivalence with a literal oracle and paired corruptions."""
import hashlib
import json
from pathlib import Path
import pytest
from arsia_pipeline import arcgis_query as aq,parser_guard
from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.errors import ValidationFailure
from arsia_pipeline.metadata_extractors import MetadataError
from test_arcgis_representation import bundle


def changed(file,text):
    Path(file['path']).write_text(text)
    file['sha256']=hashlib.sha256(text.encode()).hexdigest()


def reverse_objects(value):
    if isinstance(value,dict):return {k:reverse_objects(value[k]) for k in reversed(value)}
    if isinstance(value,list):return [reverse_objects(v) for v in value]
    return value


@pytest.mark.parametrize('change',['properties','pretty_crlf','bom'])
def test_same_complete_json_content_is_bound_with_different_original_hash(tmp_path,change):
    c,files,docs,_=bundle(tmp_path)
    text=json.dumps(reverse_objects(json.loads(docs['query']['content_bytes'])),indent=2)
    if change=='pretty_crlf':text=text.replace('\n','\r\n')
    if change=='bom':text='\ufeff'+text
    changed(files[0],text)
    proof,=aq.bind_uploads(c,files,docs,build_graph(c['source']['dataset_url'],docs,{'query'}),lambda:None)
    assert proof['upload_sha256']!=proof['response_sha256']
    assert proof['representation_replay']['equivalent'] is True
    assert proof['proofs'][0]['row_count']==3 and proof['proofs'][0]['deletion_authority'] is False
    assert [f['properties']['event_key'] for f in json.loads(text.lstrip('\ufeff'))['features']]==[0,1,2]


@pytest.mark.parametrize('change',['number','type','feature_order','drop','extra','coordinate'])
def test_every_typed_value_array_position_and_feature_is_bound(tmp_path,change):
    c,files,docs,_=bundle(tmp_path);value=json.loads(docs['query']['content_bytes'])
    if change=='number':value['features'][0]['properties']['event_key']=9007199254740993
    if change=='type':value['features'][0]['properties']['event_key']='0'
    if change=='feature_order':value['features'].reverse()
    if change=='drop':value['features'].pop()
    if change=='extra':value['unverified']='extra'
    if change=='coordinate':value['features'][0]['geometry']['coordinates'][0]+=1e-10
    changed(files[0],json.dumps(value))
    with pytest.raises(MetadataError) as error:
        aq.bind_uploads(c,files,docs,build_graph(c['source']['dataset_url'],docs,{'query'}),lambda:None)
    assert error.value.code=='ARCGIS_UPLOAD_UNBOUND'


@pytest.mark.parametrize('body',['{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}'])
def test_ambiguous_or_nonfinite_json_cannot_gain_a_conversion_receipt(body):
    with pytest.raises(ValidationFailure):
        parser_guard.call('json_signature',[{'text':body,'sha256':hashlib.sha256(body.encode()).hexdigest()}])


def test_numbers_do_not_pass_through_lossy_float_parsing():
    def sig(text):return parser_guard.call('json_signature',[{'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}])
    assert sig('{"n":9007199254740992}')!=sig('{"n":9007199254740993}')
    assert sig('{"n":0.123456789012345678901}')!=sig('{"n":0.123456789012345678902}')
    assert sig('{"n":1}')!=sig('{"n":"1"}')
