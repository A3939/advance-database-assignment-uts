import hashlib
import json

import pytest

from arsia_pipeline.metadata_extractors import GEO, RDF, MetadataError, extract, resolve_locator


def rdf(prefix='g', namespace=GEO, content=None):
    content = content or f'<{prefix}:lat>-35.2</{prefix}:lat><{prefix}:long>149.1</{prefix}:long>'
    return f'''<r:RDF xmlns:r="{RDF}" xmlns:{prefix}="{namespace}" xmlns:d="https://data.example.gov.au/resource/_abcd-1234/">
    <d:record r:about="https://data.example.gov.au/resource/_abcd-1234/row-1"><d:id>001</d:id>
    <d:location><{prefix}:SpatialThing>{content}</{prefix}:SpatialThing></d:location></d:record></r:RDF>'''.encode()


@pytest.mark.parametrize('prefix', ['g', 'geo', 'unrelatedPrefix'])
def test_rdf_actual_namespace_use_and_exact_locator(prefix):
    raw = rdf(prefix)
    result = extract(raw)
    point, = result['rdf_points']
    assert point['namespace'] == GEO and point['latitude'] == '-35.2'
    assert point['property'] == '{https://data.example.gov.au/resource/_abcd-1234/}location'
    assert point['record_literals']['{https://data.example.gov.au/resource/_abcd-1234/}id'] == ['001']
    assert result['authority'] == 'none_requires_scoped_host_verification'
    assert resolve_locator(raw, result['document_sha256'], point['longitude_locator']) == '149.1'


def test_namespace_mention_and_lookalike_do_not_create_coordinate_fact():
    assert extract(f'<r:RDF xmlns:r="{RDF}" xmlns:geo="{GEO}"/>'.encode())['rdf_points'] == []
    assert extract(rdf(namespace='https://attacker.example/wgs84_pos#'))['rdf_points'] == []
    assert extract(f'<root>latitude longitude {GEO}</root>'.encode())['rdf_points'] == []


@pytest.mark.parametrize('raw', [
    b'<!DOCTYPE root [<!ENTITY x "expanded">]><root>&x;</root>',
    b'<!DOCTYPE root SYSTEM "https://example.org/dtd"><root/>',
    b'<root>',
    rdf(content='<g:lat>-35</g:lat><g:lat>-36</g:lat><g:long>149</g:long>'),
])
def test_xml_entities_external_resources_and_conflicting_literals_rejected(raw):
    with pytest.raises(MetadataError):
        extract(raw)


def test_html_href_is_preserved_but_not_promoted_to_delegation():
    raw = b'<html><body><a href="https://cdn.example/data?a=1&amp;b=2">download</a><script type="application/ld+json">{"@context":"https://schema.org","@type":"Dataset"}</script></body></html>'
    result = extract(raw)
    assert result['links'][0]['href'] == 'https://cdn.example/data?a=1&b=2'
    assert result['links'][0]['role'] == 'discovery_candidate'
    # Remote context remains inert text; this extractor has no URL loader.
    assert result['json_ld'][0]['@context'] == 'https://schema.org'


def test_raw_json_pointer_preserves_literal_slashes_and_array_order():
    raw = json.dumps({'a/b~': ['latitude', 'longitude']}).encode()
    digest = hashlib.sha256(raw).hexdigest()
    assert resolve_locator(raw, digest, {'kind': 'json-pointer', 'pointer': '/a~1b~0/0'}) == 'latitude'
    assert resolve_locator(raw, digest, {'kind': 'json-pointer', 'pointer': ''}) == {'a/b~': ['latitude', 'longitude']}
    for pointer in ['/a~1b~0/-1', '/a~1b~0/00', '/a~2b/0', '/missing']:
        with pytest.raises(MetadataError):
            resolve_locator(raw, digest, {'kind': 'json-pointer', 'pointer': pointer})
    with pytest.raises(MetadataError, match='pinned'):
        resolve_locator(raw + b' ', digest, {'kind': 'json-pointer', 'pointer': ''})


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"value":NaN}', b'[[', b'['*100 + b'0' + b']'*100])
def test_ambiguous_or_unbounded_json_metadata_rejected(raw):
    with pytest.raises(MetadataError):
        extract(raw)


def test_xml_locator_cannot_select_same_local_name_in_other_namespace():
    raw = rdf()
    result = extract(raw)
    locator = result['rdf_points'][0]['latitude_locator']
    locator['path'][-1][0] = '{https://other.example/}lat'
    with pytest.raises(MetadataError):
        resolve_locator(raw, result['document_sha256'], locator)
