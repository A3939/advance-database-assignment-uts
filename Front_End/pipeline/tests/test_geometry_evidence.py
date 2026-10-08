import copy
import json

import pytest

from arsia_pipeline.evidence_grounding import ground_contract
from arsia_pipeline.geography_review import coordinate_evidence, coordinate_crs_matches
from arsia_pipeline.geometry_evidence import geometry_metadata
from arsia_pipeline.intakereaders import detect_tables
from arsia_pipeline.errors import NeedsInput


def collection(geometry=None):
    return {'features': [{'type': 'Feature', 'properties': {'ID': 'a', 'Date': '2024-01-01'},
                          'geometry': geometry or {'type': 'Point', 'coordinates': [149.1, -35.2, 600]}}],
            'type': 'FeatureCollection'}


def proposal():
    url = 'https://data.example.gov.au/resource/wxyz-9876.geojson'
    contract = {'source': {'dataset_url': url}, 'resources': [{'role': 'events', 'grain': 'crash', 'key': ['ID'],
               'mapping': {'date': {'field': 'Date'}, 'geography': {'x_field': '__geometry_x', 'y_field': '__geometry_y', 'crs': 'EPSG:4326'}}}]}
    return url, contract, {claim: [{'document_id': 'official'}] for claim in ('source_identity', 'grain', 'date', 'geography')}


def test_geojson_geometry_crs_reaches_field_and_crs_grounding(tmp_path):
    url, contract, accepted = proposal()
    data = collection()
    doc = {'url': url, 'text': json.dumps(data)}
    result = ground_contract(contract, {'official': doc}, accepted)
    assert result['ok'], result
    path = tmp_path / 'renamed.json'; path.write_text(doc['text'])
    table, = detect_tables({'path': str(path)})
    assert table['json_kind'] == 'geojson' and table['observed_geometry_types'] == ['Point']
    assert table['geojson_default_crs'] == 'OGC:CRS84'
    assert coordinate_evidence('official', doc, 'ID', 'Date') == []


def test_legacy_geojson_is_not_silently_wgs84():
    data = collection(); data['crs'] = {'type': 'name', 'properties': {'name': 'EPSG:4283'}}
    point, refs = geometry_metadata(data)
    assert point and len(refs) == 1
    assert coordinate_crs_matches(refs[0], 'EPSG:4283')
    assert not coordinate_crs_matches(refs[0], 'EPSG:4326')


@pytest.mark.parametrize('kind,coordinates', [('LineString', [[149,-35],[150,-36]]), ('Polygon', [[[149,-35],[150,-36],[149,-35]]]), ('MultiPoint', [[149,-35],[150,-36]])])
def test_nonpoint_geometry_is_preserved_and_never_accepted_as_point(tmp_path, kind, coordinates):
    data = collection({'type': kind, 'coordinates': coordinates})
    path = tmp_path / 'shapes.json'; path.write_text(json.dumps(data))
    table, = detect_tables({'path': str(path)})
    assert table['observed_geometry_types'] == [kind]
    assert geometry_metadata(data) == (False, [])


def test_nested_other_layer_cannot_supply_geometry_crs():
    doc = {'text': json.dumps({'fields': [{'name': 'ID'}], 'other_layer': {'geometryType': 'esriGeometryPoint', 'spatialReference': {'wkid': 4326}}})}
    assert coordinate_evidence('layer', doc, '__geometry_x', '__geometry_y') == []


def test_query_reference_is_not_overridden_by_layer_extent():
    data = {'geometryType': 'esriGeometryPoint', 'spatialReference': {'wkid': 4326},
            'extent': {'spatialReference': {'wkid': 3857}}, 'features': [{'attributes': {}, 'geometry': {'x': 149, 'y': -35}}]}
    point, refs = geometry_metadata(data)
    assert point and len(refs) == 1 and refs[0]['code'] == '4326'


def test_wkt_and_per_geometry_reference_are_retained(tmp_path):
    from pyproj import CRS
    data = {'features': [{'attributes': {'ID': 1}, 'geometry': {'x': 149, 'y': -35, 'spatialReference': {'wkt': CRS.from_epsg(4326).to_wkt()}}}],
            'geometryType': 'esriGeometryPoint'}
    point, refs = geometry_metadata(data)
    assert point and coordinate_crs_matches(refs[0], 'EPSG:4326')
    path = tmp_path / 'query.json'; path.write_text(json.dumps(data))
    table, = detect_tables({'path': str(path)})
    assert table['geometry_spatial_references'][0]['reference']['wkt'] == data['features'][0]['geometry']['spatialReference']['wkt']


def test_mutually_exclusive_declarations_do_not_pass_by_matching_one():
    url = 'https://data.example.gov.au/services/roads/FeatureServer/0'
    _, contract, accepted = proposal(); contract['source']['dataset_url'] = url
    data = {'id': 0, 'fields': [{'name': 'ID'}, {'name': 'Date'}], 'geometryType': 'esriGeometryPoint',
            'spatialReference': {'wkid': 4326, 'latestWkid': 4283}}
    result = ground_contract(contract, {'official': {'url': url, 'text': json.dumps(data)}}, accepted)
    assert any(i['code'] == 'CRS_EVIDENCE_CONFLICT' for i in result['issues'])


@pytest.mark.parametrize('where', ['feature', 'geometry'])
def test_inner_crs_cannot_silently_inherit_rfc7946(tmp_path, where):
    data = collection()
    node = data['features'][0] if where == 'feature' else data['features'][0]['geometry']
    node['crs'] = {'type': 'name', 'properties': {'name': 'EPSG:4283'}}
    path = tmp_path / 'legacy.json'; path.write_text(json.dumps(data))
    with pytest.raises(NeedsInput):
        detect_tables({'path': str(path)})


def test_registered_public_geojson_supplies_schema_without_exposing_rows(tmp_path, monkeypatch):
    import hashlib
    from arsia_pipeline import config
    from arsia_pipeline.intake_tools import IntakeTools
    from arsia_pipeline.trusted_qa import _proof
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    url, contract, _ = proposal()
    data = collection(); data['features'][0]['properties']['ID'] = 'sensitive-record-value'
    raw = json.dumps(data).encode(); sha = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'sha256').mkdir(); path = tmp_path / 'sha256' / sha; path.write_bytes(raw)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'status': 'fetched', 'sha256': sha, 'final_url': url, 'final_host_official': True}))
    file = {'id': 'official-fetch', 'name': 'sample.geojson', 'path': str(path), 'sha256': sha, 'size': len(raw),
            'evidence_url': url, 'receipt_path': str(receipt), 'role': 'public_evidence'}
    output = IntakeTools([file], tmp_path / 'tools').read_document(file['id'])
    assert 'sensitive-record-value' not in json.dumps(output)
    assert '149.1' not in output['text'] and 'fields' in output['text']
    contract['documents'] = output['__documents']
    contract['resources'][0]['file_id'] = 'upload'
    contract['evidence'] = {claim: [{'document_id': output['document_id'], 'quote': output['text']}]
                            for claim in ('source_identity', 'grain', 'date', 'geography', 'coverage_update')}
    result = _proof(contract, tmp_path)
    assert result['grounding']['ok']
    # Upload labels cannot elevate raw user feature records to source evidence.
    user_file = {k: v for k, v in file.items() if k not in ('role', 'receipt_path', 'evidence_url')}
    with pytest.raises(NeedsInput, match='JSON records'):
        IntakeTools([user_file], tmp_path / 'uploaded-tools').read_document(user_file['id'])
