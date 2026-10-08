import copy
import pytest
from arsia_pipeline.arcgis_query import object_id_field
from arsia_pipeline.metadata_extractors import MetadataError

@pytest.mark.parametrize('name,layer',[('fid_27',7),('RowKey',91),('objectid',45)])
@pytest.mark.parametrize('service,explicit',[('MapServer',False),('MapServer',True),('FeatureServer',True)])
def test_exact_protocol_oid(name,layer,service,explicit):
    m={'fields':[{'name':'LABEL','type':'esriFieldTypeString'},{'name':name,'type':'esriFieldTypeOID'}]}
    if explicit:m['objectIdField']=name
    assert object_id_field(m,f'https://records.example.gov.au/rest/services/Other/{service}/{layer}')==name

@pytest.mark.parametrize('fault',['missing','multiple','wrong_type','wrong_case','duplicate','conflicting_response','empty_top','feature_missing','hashed'])
def test_ambiguous_missing_or_conflicting_oid_rejected(fault):
    m={'fields':[{'name':'Key','type':'esriFieldTypeOID'},{'name':'Name','type':'esriFieldTypeString'}],'objectIdField':'Key'}
    service='MapServer'
    if fault=='missing':m['fields']=m['fields'][1:]
    elif fault=='multiple':m['fields'].append({'name':'Other','type':'esriFieldTypeOID'})
    elif fault=='wrong_type':m['objectIdField']='Name'
    elif fault=='wrong_case':m['objectIdField']='KEY'
    elif fault=='duplicate':m['fields'].append(dict(m['fields'][0]))
    elif fault=='conflicting_response':m['objectIdFieldName']='Other'
    elif fault=='empty_top':m['objectIdField']=None
    elif fault=='feature_missing':service='FeatureServer';del m['objectIdField']
    else:m['OIDFieldContainsHashValue']=True
    with pytest.raises(MetadataError):object_id_field(m,f'https://records.example.gov.au/rest/services/Other/{service}/83')

@pytest.mark.parametrize('name',['shape_value','otherGeom'])
def test_geometry_field_is_not_an_ordinary_attribute(name):
    from test_arcgis_representation import fixture
    from arsia_pipeline.arcgis_query import parse,verify_response
    _,_,url,m,r,_=fixture()
    m['fields'].append({'name':name,'type':'esriFieldTypeGeometry'})
    assert verify_response(parse(url),m,r)['row_count']==3
    m['fields'][-1]['type']='esriFieldTypeString'
    with pytest.raises(MetadataError,match='Response fields'):verify_response(parse(url),m,r)


def test_root_service_path_retains_published_oid_support():
    assert object_id_field({'objectIdField':'ID','fields':[{'name':'ID','type':'esriFieldTypeOID'}]},'https://source.gov.au/FeatureServer/0')=='ID'
