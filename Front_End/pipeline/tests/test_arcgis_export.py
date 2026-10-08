import copy

import pytest

from arsia_pipeline.arcgis_export import preserve_page
from arsia_pipeline.errors import NeedsInput, UnsupportedCapability, ValidationFailure


def fixture():
    metadata = {'geometryType': 'esriGeometryPoint', 'extent': {'spatialReference': {'wkid': 3857}}}
    page = {'geometryType': 'esriGeometryPoint', 'spatialReference': {'wkid': 4326},
            'features': [{'attributes': {'ID': 1}, 'geometry': {'x': 149.1, 'y': -35.2, 'z': 600, 'm': 5}}]}
    return metadata, page


def test_explicit_page_reference_is_preserved_instead_of_extent_or_requested_reference():
    metadata, page = fixture(); original = copy.deepcopy(page)
    features, evidence = preserve_page(metadata, page, requested_reference={'wkid': 3857})
    assert page == original
    assert features[0]['geometry'] == {**original['features'][0]['geometry'], 'spatialReference': {'wkid': 4326}}
    assert evidence['reference_origins'] == {'page': 1}
    assert evidence['coordinates_modified'] is False


def test_per_geometry_reference_is_not_overridden_by_page():
    metadata, page = fixture(); page['features'][0]['geometry']['spatialReference'] = {'wkid': 4283}
    features, evidence = preserve_page(metadata, page)
    assert features == page['features']
    assert evidence['reference_origins'] == {'feature': 1}


@pytest.mark.parametrize('reference', [{'wkid': 102100, 'latestWkid': 3857}, {'wkt': 'Frozen source WKT retained for QA interpretation'}])
def test_explicit_reference_representation_survives_without_invented_epsg_label(reference):
    metadata, page = fixture(); page['spatialReference'] = reference
    features, _ = preserve_page(metadata, page)
    assert features[0]['geometry']['spatialReference'] == reference


def test_missing_page_reference_may_use_only_an_explicit_request():
    metadata, page = fixture(); page.pop('spatialReference')
    with pytest.raises(NeedsInput) as failed:
        preserve_page(metadata, page)
    assert failed.value.details['code'] == 'ARCGIS_GEOMETRY_REFERENCE_MISSING'
    features, receipt = preserve_page(metadata, page, requested_reference={'wkid': 3857})
    assert features[0]['geometry']['spatialReference'] == {'wkid': 3857}
    assert receipt['reference_origins'] == {'requested_outSR': 1}


@pytest.mark.parametrize('target', ['page', 'feature'])
def test_quantized_coordinates_are_not_silently_interpreted_as_plain_xy(target):
    metadata, page = fixture()
    (page if target == 'page' else page['features'][0]['geometry'])['transform'] = {'scale': [1, 1], 'translate': [100, 100]}
    with pytest.raises(UnsupportedCapability) as failure:
        preserve_page(metadata, page)
    assert failure.value.code == 'ARCGIS_QUANTIZED_GEOMETRY_UNSUPPORTED'
    assert failure.value.details['blockers'][0]['responsible_party'] == 'system'
    assert failure.value.questions == []


@pytest.mark.parametrize('change', ['geometry_type', 'date_reference'])
def test_conflicting_page_semantics_are_not_lost_during_combination(change):
    metadata, page = fixture()
    if change == 'geometry_type': page['geometryType'] = 'esriGeometryPolygon'
    else: page['dateFieldsTimeReference'] = {'timeZone': 'Unrelated zone'}
    with pytest.raises(ValidationFailure): preserve_page(metadata, page)


def test_null_geometry_does_not_need_a_fabricated_reference():
    metadata, page = fixture(); page.pop('spatialReference'); page['features'][0]['geometry'] = None
    features, receipt = preserve_page(metadata, page)
    assert features == page['features'] and receipt['reference_origins'] == {'null_geometry': 1}


@pytest.mark.parametrize('bad', [{}, 'EPSG:4326', {'wkid': True}, {'unrelated': 4326}])
def test_malformed_reference_is_not_treated_as_absent(bad):
    metadata, page = fixture(); page['spatialReference'] = bad
    with pytest.raises(NeedsInput): preserve_page(metadata, page)
