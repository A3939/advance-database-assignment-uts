"""Representation changes must not change the meaning of an uploaded table."""
import itertools
import json

import pytest

from arsia_pipeline.errors import NeedsInput, ValidationFailure
from arsia_pipeline.intakereaders import _json_layout, detect_tables, iter_table


def write(tmp_path, value):
    path = tmp_path / 'source.json'
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize('order', list(itertools.permutations(('type', 'features', 'bbox'))))
def test_geojson_member_order_preserves_meaning(tmp_path, order):
    body = {'type': 'FeatureCollection', 'bbox': [149, -36, 150, -35], 'features': [
        {'type': 'Feature', 'properties': {'ID': '001'},
         'geometry': {'type': 'Point', 'coordinates': [149.1, -35.2, 600]}}]}
    path = write(tmp_path, {key: body[key] for key in order})
    table = detect_tables(path)[0]
    assert table['json_kind'] == 'geojson'
    assert table['geojson_default_crs'] == 'OGC:CRS84'
    row = list(iter_table(path, table))[0][1]
    assert row['ID'] == '001'
    assert row['__geometry']['coordinates'] == ['149.1', '-35.2', 600]


@pytest.mark.parametrize('order', list(itertools.permutations(('spatialReference', 'features', 'geometryType'))))
def test_arcgis_metadata_after_features_is_retained(tmp_path, order):
    body = {'spatialReference': {'wkid': 102100, 'latestWkid': 3857},
            'geometryType': 'esriGeometryPoint',
            'features': [{'attributes': {'ID': 1}, 'geometry': {'x': 10, 'y': 20}}]}
    table = detect_tables(write(tmp_path, {key: body[key] for key in order}))[0]
    assert table['spatial_reference'] == 3857
    assert table['spatial_reference_definition'] == body['spatialReference']


def test_large_collection_metadata_is_not_limited_by_feature_events(tmp_path):
    body = {'features': [{'attributes': {'ID': i}, 'geometry': {'x': 1, 'y': 2}}
                         for i in range(5000)], 'spatialReference': {'wkid': 4326}}
    assert _json_layout(write(tmp_path, body))['spatial_reference'] == 4326


@pytest.mark.parametrize('body', [
    {'features': [], 'type': 'Point'},
    {'type': 'FeatureCollection', 'features': [], 'spatialReference': {'wkid': 3857}},
    {'type': 'FeatureCollection', 'features': {}},
])
def test_conflicting_feature_envelopes_rejected(tmp_path, body):
    with pytest.raises(ValidationFailure):
        _json_layout(write(tmp_path, body))


def test_legacy_crs_never_inherits_rfc7946_default(tmp_path):
    body = {'features': [], 'crs': {'type': 'name', 'properties': {'name': 'EPSG:3112'}},
            'type': 'FeatureCollection'}
    result = _json_layout(write(tmp_path, body))
    assert result['geojson_default_crs'] is None
    assert result['spatial_reference'] == 'EPSG:3112'


@pytest.mark.parametrize('raw', [
    '{"features":[],"type":"FeatureCollection","type":"FeatureCollection"}',
    '{"features":[],"spatialReference":{"wkid":4326,"wkid":3857}}',
    '{"features":[{"attributes":{"ID":1,"ID":2}}]}',
    '{"features":[],"tail":NaN}',
    '{"features":[]} {"features":[]}',
    '{"features":[],',
])
def test_malformed_envelope_cannot_hide_after_feature_array(tmp_path, raw):
    path = tmp_path / 'bad.json'
    path.write_text(raw)
    with pytest.raises(ValidationFailure):
        _json_layout(path)


def test_json_header_covers_late_fields(tmp_path):
    path = write(tmp_path, [{'ID': i} for i in range(1000)] + [{'ID': 1000, 'late': 'x'}])
    table = detect_tables(path)[0]
    assert table['header'] == ['ID', 'late']
    assert table['header_complete'] is True
    assert table['header_inspected_records'] == 1001


def test_hints_cannot_relabel_geometry_as_plain_records(tmp_path):
    path = write(tmp_path, {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'ID': 1}, 'geometry': None}]})
    with pytest.raises(ValidationFailure):
        detect_tables(path, {'record_path': 'features.item', 'json_kind': 'records'})


def test_multiple_record_arrays_require_explicit_selection(tmp_path):
    path = write(tmp_path, {'data': [{'ID': 1}], 'records': [{'ID': 2}]})
    with pytest.raises(NeedsInput):
        detect_tables(path)
    assert list(iter_table(path, {'format': 'json', 'record_path': 'records.item'}))[0][1]['ID'] == 2


@pytest.mark.parametrize('coords', [[149, -35, 1, 2], ['149', -35], [True, -35], [149], [149, -135]])
def test_rfc_point_invalid_ordinates_cannot_be_coerced(tmp_path, coords):
    path = write(tmp_path, {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'ID': 1}, 'geometry': {'type': 'Point', 'coordinates': coords}}]})
    with pytest.raises(ValidationFailure):
        detect_tables(path)


def test_null_and_nonpoint_geometry_remain_explicit(tmp_path):
    line = {'type': 'LineString', 'coordinates': [[149, -35], [150, -36]]}
    path = write(tmp_path, {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': {'ID': 1}, 'geometry': None},
        {'type': 'Feature', 'properties': {'ID': 2}, 'geometry': line}]})
    rows = [r for _, r in iter_table(path)]
    assert [r['__geometry'] for r in rows] == [None, line]
    assert all(r['__geometry_x'] is None and r['__geometry_y'] is None for r in rows)


def test_supplied_header_cannot_bypass_envelope_check(tmp_path):
    path = write(tmp_path, {'type': 'FeatureCollection', 'features': []})
    with pytest.raises(ValidationFailure):
        list(iter_table(path, {'format': 'json', 'record_path': 'features.item',
                              'json_kind': 'records', 'header': ['ID']}))


def test_envelope_scan_can_be_cancelled(tmp_path):
    from arsia_pipeline.errors import ImportCancelled
    path = write(tmp_path, {'features': [{'attributes': {'ID': i}} for i in range(1000)]})
    calls = 0
    def cancelled():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ImportCancelled('cancelled during envelope scan')
    with pytest.raises(ImportCancelled):
        _json_layout(path, check_cancelled=cancelled)
    assert calls == 2
