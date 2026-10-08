import json

import pytest

from arsia_pipeline.evidence_graph import build_graph, identity, representation
from arsia_pipeline.metadata_extractors import GEO, RDF

SOURCE = 'https://data.example.gov.au/dataset/events'
CATALOGUE = 'https://data.example.gov.au/api/3/action/package_show?id=events'
CDN = 'https://storage.example/files/events.csv?version=2'


def doc(url, value):
    raw = (json.dumps(value) if isinstance(value, dict) else value).encode()
    return {'url': url, 'content_bytes': raw, 'text': raw.decode()}


def catalog(url=CDN):
    return doc(CATALOGUE, {'result': {'name': 'events', 'id': 'event-uuid',
                                     'resources': [{'id': 'resource-1', 'url': url}]}})


def test_explicit_publisher_distribution_binds_only_exact_external_resource():
    docs = {'catalogue': catalog(), 'file': doc(CDN, 'ID,Date\n1,2024-01-01'),
            'other': doc(CDN.replace('version=2', 'version=3'), 'ID,Date\n1,2024-01-01')}
    graph = build_graph(SOURCE, docs, {'catalogue'})
    assert graph['authorized'] == {'catalogue', 'file'}
    edge, = graph['proof']['edges']
    assert edge['predicate'] == 'distributes_resource'
    assert edge['locator']['pointer'] == '/result/resources/0/url'


@pytest.mark.parametrize('mode', ['backlink', 'footer', 'shared_host', 'normative_only'])
def test_discovery_links_cannot_grant_authority(mode):
    documents = {'catalogue': catalog()}
    if mode == 'backlink':
        documents['unrelated'] = doc('https://other.example.gov.au/dict', {'url': CATALOGUE, 'fields': [{'name': 'ID'}]})
    elif mode == 'footer':
        documents['catalogue'] = doc(CATALOGUE, {'result': {'name': 'events', 'resources': [], 'footer': {'url': CDN}}})
        documents['unrelated'] = doc(CDN, 'Official ID Date dictionary')
    elif mode == 'shared_host':
        documents['unrelated'] = doc('https://data.example.gov.au/dataset/unrelated', {'fields': [{'name': 'ID'}]})
    else:
        documents['unrelated'] = doc('https://www.w3.org/2003/01/geo/wgs84_pos', 'ID Date WGS84')
    assert 'unrelated' not in build_graph(SOURCE, documents, {'catalogue'})['authorized']


def test_external_resource_cannot_delegate_further():
    docs = {'catalogue': catalog(), 'file': doc(CDN, {'resources': [{'url': 'https://evil.example/dict'}]}),
            'third': doc('https://evil.example/dict', 'Official ID Date dictionary')}
    assert build_graph(SOURCE, docs, {'catalogue'})['authorized'] == {'catalogue', 'file'}


def test_ckan_distribution_rule_does_not_reinterpret_arbitrary_provider_keys():
    source = 'https://data.example.gov.au/resource/abcd-1234'
    docs = {'schema': doc('https://data.example.gov.au/api/views/abcd-1234.json',
                         {'id': 'abcd-1234', 'columns': [], 'resources': [{'url': CDN}]}),
            'external': doc(CDN, 'ID Date')}
    assert build_graph(source, docs, {'schema'})['authorized'] == {'schema'}


def test_unverified_publisher_receipt_and_model_role_never_anchor():
    value = catalog()
    value.update(publisher_verified=False, role='publisher_dataset', confirmed=True)
    assert not build_graph(SOURCE, {'catalogue': value}, {'catalogue'})['anchors']
    assert not build_graph(SOURCE, {'catalogue': catalog()}, set())['anchors']


def test_catalogue_search_selects_one_package_and_preserves_locator():
    docs = {'search': doc('https://data.example.gov.au/api/3/action/package_search?q=crash', {'result': {'results': [
        {'name': 'unrelated', 'resources': [{'url': 'https://cdn.example/wrong'}]},
        {'name': 'events', 'id': 'uuid', 'resources': [{'url': CDN}]}]}}),
        'file': doc(CDN, 'data'), 'wrong': doc('https://cdn.example/wrong', 'ID Date')}
    graph = build_graph(SOURCE, docs, {'search'})
    assert graph['authorized'] == {'search', 'file'}
    assert graph['proof']['edges'][0]['locator']['pointer'] == '/result/results/1/resources/0/url'


def test_no_global_www_or_http_alias_and_query_scope_retained():
    a = 'https://data.example.gov.au/resource/abcd-1234.json?$limit=1'
    b = 'https://data.example.gov.au/resource/abcd-1234.json?$limit=100'
    assert identity(a) == identity(b)
    assert representation(a) != representation(b)
    assert identity(a) != identity(a.replace('://data.', '://www.data.'))
    assert representation(a.replace('https:', 'http:')) is None


def test_actual_rdf_usage_connects_normative_definition_without_granting_field_authority():
    source = 'https://data.example.gov.au/resource/abcd-1234'
    url = 'https://data.example.gov.au/api/views/abcd-1234.json'
    rdf = f'<r:RDF xmlns:r="{RDF}" xmlns:g="{GEO}" xmlns:d="https://data.example.gov.au/resource/_abcd-1234/"><d:row><d:location><g:Point><g:lat>-35</g:lat><g:long>149</g:long></g:Point></d:location></d:row></r:RDF>'
    docs = {'metadata': doc(url, {'id': 'abcd-1234', 'columns': []}),
            'sample': doc(source + '.rdf?$limit=1', rdf),
            'definition': doc('https://www.w3.org/2003/01/geo/wgs84_pos', 'WGS84 definition')}
    graph = build_graph(source, docs, {'metadata'})
    assert graph['authorized'] == {'metadata', 'sample'}
    assert any(e['predicate'] == 'uses_vocabulary' and e['to'] == 'definition' for e in graph['proof']['edges'])
    assert not any('record_literals' in str(node) for node in graph['proof']['nodes'])


def test_delegated_source_url_has_a_publisher_anchor():
    graph = build_graph(CDN, {'catalogue': catalog(), 'file': doc(CDN, 'data')}, {'catalogue'})
    assert graph['anchors'] == {'catalogue'}
    assert graph['authorized'] == {'catalogue', 'file'}


@pytest.mark.parametrize('source,url,value', [
    (SOURCE, CATALOGUE, {'result': {'name': 'other', 'resources': []}}),
    ('https://data.example.gov.au/resource/abcd-1234', 'https://data.example.gov.au/api/views/abcd-1234.json', {'id': 'wxyz-9876', 'columns': []}),
    ('https://data.example.gov.au/rest/services/events/FeatureServer/0', 'https://data.example.gov.au/rest/services/events/FeatureServer/0?f=json', {'id': 1, 'fields': []}),
])
def test_endpoint_and_body_identity_conflicts_are_preserved(source, url, value):
    from arsia_pipeline.metadata_extractors import MetadataError
    with pytest.raises(MetadataError) as error:
        build_graph(source, {'metadata': doc(url, value)}, {'metadata'})
    assert error.value.code == 'SOURCE_METADATA_ID_CONFLICT'


def test_verified_external_dictionary_is_admitted_only_by_exact_distribution(tmp_path, monkeypatch):
    from arsia_pipeline import config
    from arsia_pipeline.trusted_qa import _proof
    from arsia_pipeline.errors import NeedsInput
    import hashlib
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    docs = {'catalogue': catalog(), 'dictionary': doc(CDN, 'ID identifies a reported event. Date defines the crash date.')}
    contract = {'source': {'dataset_url': SOURCE},
                'resources': [{'role': 'crash', 'grain': 'crash', 'key': ['ID'], 'file_id': 'file',
                               'mapping': {'date': {'field': 'Date'}}}], 'documents': [], 'evidence': {}}
    (tmp_path / 'sha256').mkdir()
    for key, document in docs.items():
        sha = hashlib.sha256(document['content_bytes']).hexdigest()
        (tmp_path / 'sha256' / sha).write_bytes(document['content_bytes'])
        receipt = tmp_path / (key + '.json')
        receipt.write_text(json.dumps({'status': 'fetched', 'final_url': document['url'],
                                     'final_host_official': key == 'catalogue', 'sha256': sha}))
        contract['documents'].append({'document_id': key, 'receipt_path': str(receipt)})
    for claim in ('source_identity', 'coverage_update', 'grain', 'date'):
        key = 'catalogue' if claim in ('source_identity', 'coverage_update') else 'dictionary'
        contract['evidence'][claim] = [{'document_id': key, 'quote': docs[key]['text']}]
    proof = _proof(contract, tmp_path)
    assert proof['grain'][0]['url'] == CDN
    receipt = tmp_path / 'dictionary.json'
    value = json.loads(receipt.read_text()); value['final_url'] = CDN.replace('version=2', 'version=3')
    receipt.write_text(json.dumps(value))
    with pytest.raises(NeedsInput) as error:
        _proof(contract, tmp_path)
    assert any(i['code'] == 'CLAIM_SCOPE_UNBOUND' for i in error.value.details['grounding']['issues'])
