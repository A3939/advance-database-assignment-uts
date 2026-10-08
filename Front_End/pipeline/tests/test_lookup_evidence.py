"""Synthetic publisher chains verify general scope, never real-source approval."""
import copy
import hashlib
import json

import pytest

from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.evidence_grounding import ground_contract, _critical_fields
from arsia_pipeline.evidence_references import reference
from arsia_pipeline.lookup_evidence import review_lookup_relations, CONTEXT
from arsia_pipeline.lookup_semantics import field_origin, geography_resources
from arsia_pipeline.errors import NeedsInput, UnsupportedCapability, ValidationFailure
from arsia_pipeline.metadata_extractors import MetadataError
from test_canonical_v2 import contract

SOURCE = 'https://data.example.gov.au/dataset/events'
CHILD = 'https://cdn.example/events.csv'
PARENT = 'https://cdn.example/codes.csv'


def document(url, value):
    raw = (json.dumps(value) if not isinstance(value, str) else value).encode()
    return {'url': url, 'content_bytes': raw, 'text': raw.decode(), 'sha256': hashlib.sha256(raw).hexdigest()}


def fixture():
    c = contract()
    c['source'].update(dataset_url=SOURCE, coverage={'from': '2024-01-01', 'to': '2024-12-31'})
    r = c['resources'][0]
    r.update(source_url=CHILD)
    r['mapping'] = {'date': {'field': 'DATE'}, 'severity': {'field': {'lookup': 'code', 'field': 'Class'}, 'categories': {}},
                    'geography': {'x_field': {'lookup': 'code', 'field': 'X'}, 'y_field': {'lookup': 'code', 'field': 'Y'}, 'crs': 'EPSG:4326'}}
    r['lookups'] = [{'name': 'code', 'parent': 'codes', 'fields': ['Type'], 'select': ['Class', 'X', 'Y'], 'allow_blank': False, 'on_missing': 'error'}]
    c['lookup_tables'] = [{'role': 'codes', 'purpose': 'lookup', 'file_id': 'parent', 'source_url': PARENT, 'table': {}, 'key': ['Code']}]
    docs = {
        'child': document('https://cdn.example/child.json', {'fields': [{'name': name} for name in ['ID', 'DATE', 'Type', 'Class', 'X', 'Y']]}),
        'parent': document('https://cdn.example/parent.json', {'@context': 'https://schema.org', '@type': 'DigitalDocument',
            'about': PARENT, 'temporalCoverage': '2024-01-01/2025-01-01', 'fields': [{'name': name} for name in ['Code', 'Class', 'X', 'Y']]}),
        'geo': document('https://cdn.example/geo.txt', 'X and Y coordinates use the datum EPSG:4326.'),
        'relations': document('https://cdn.example/relations.json', {'@context': CONTEXT, 'url': CHILD,
            'tableSchema': {'columns': [{'name': 'Type', 'required': False}], 'foreignKeys': [
                {'columnReference': ['Type'], 'reference': {'resource': PARENT, 'columnReference': ['Code']}}]}}),
    }
    docs['catalogue'] = document('https://data.example.gov.au/api/3/action/package_show?id=events',
        {'result': {'name': 'events', 'resources': [
            {'id': key, 'url': CHILD if key in {'child', 'relations'} else PARENT, 'metadata_url': doc['url']}
            for key, doc in docs.items()]}})
    accepted = {claim: [{'document_id': key, 'quote': doc['text']} for key, doc in docs.items()]
                for claim in ('grain', 'date', 'severity', 'geography', 'coverage_update', 'relations')}
    accepted['source_identity'] = [{'document_id': 'catalogue', 'quote': docs['catalogue']['text']}]
    accepted['relations'].append(reference(docs['relations']['content_bytes'], docs['relations']['sha256'], 'relations',
                                           {'kind': 'json-pointer', 'pointer': ''}))
    return c, docs, accepted


def replace(docs, key, value):
    docs[key] = document(docs[key]['url'], value)


def evaluate(c, docs, accepted):
    graph = build_graph(SOURCE, docs, {'catalogue'})
    grounding = ground_contract(c, docs, accepted, graph=graph)
    relation = review_lookup_relations(c, graph, grounding, accepted)
    return grounding, relation


def test_parent_fields_and_crs_are_bound_to_parent_resource_not_child(tmp_path):
    c, docs, accepted = fixture()
    original = copy.deepcopy(c)
    grounding, relation = evaluate(c, docs, accepted)
    assert grounding['ok'], grounding
    assert relation['ok'], relation
    fields = {(b['role'], b['claim'], b['field']) for b in grounding['field_bindings']}
    assert ('codes', 'severity', 'Class') in fields
    assert ('codes', 'geography', 'X') in fields
    assert ('crash', 'relations', 'Type') in fields
    assert ('codes', 'relations', 'Code') in fields
    assert ('crash', 'severity', 'Class') not in fields
    assert grounding['applicability']['roles']['codes']['applicable_documents'] == ['catalogue', 'geo', 'parent']
    view = geography_resources(c)[0]
    assert (view['role'], view['file_id'], view['source_url'], view['key']) == ('codes', 'parent', PARENT, ['Code'])
    assert view['mapping']['geography']['x_field'] == 'X'
    assert c == original


def test_child_dictionary_with_same_field_names_cannot_certify_parent(tmp_path):
    c, docs, accepted = fixture()
    accepted['severity'] = [{'document_id': 'child', 'quote': docs['child']['text']}]
    grounding, _ = evaluate(c, docs, accepted)
    assert any(i['code'] == 'MAPPED_FIELD_UNGROUNDED' and i['role'] == 'codes' and i['field'] == 'Class' for i in grounding['issues'])


@pytest.mark.parametrize('fault', ['wrong_resource', 'wrong_time', 'missing_parent_url', 'forged_parent_url'])
def test_parent_applicability_is_not_inherited_from_child(tmp_path, fault):
    c, docs, accepted = fixture()
    value = json.loads(docs['parent']['content_bytes'])
    if fault == 'wrong_resource': value['about'] = CHILD
    if fault == 'wrong_time': value['temporalCoverage'] = '2010-01-01/2011-01-01'
    if fault == 'missing_parent_url': c['lookup_tables'][0].pop('source_url')
    if fault == 'forged_parent_url': c['lookup_tables'][0]['source_url'] = 'https://attacker.example/codes.csv'
    replace(docs, 'parent', value)
    grounding, relation = evaluate(c, docs, accepted)
    assert not grounding['ok']
    if fault in {'missing_parent_url', 'forged_parent_url'}:
        assert not relation['ok'] or any(i['code'] == 'RESOURCE_IDENTITY_UNBOUND' for i in grounding['issues'])


def test_parent_crs_conflict_cannot_be_omitted_by_citing_only_child(tmp_path):
    c, docs, accepted = fixture()
    docs['other_geo'] = document('https://cdn.example/other-geo.txt', 'X and Y coordinates use the datum EPSG:4283.')
    catalogue = json.loads(docs['catalogue']['content_bytes'])
    catalogue['result']['resources'].append({'id': 'other', 'url': PARENT, 'metadata_url': docs['other_geo']['url']})
    replace(docs, 'catalogue', catalogue)
    grounding, _ = evaluate(c, docs, accepted)
    assert any(i['code'] == 'CRS_EVIDENCE_CONFLICT' and i['role'] == 'codes' for i in grounding['issues'])


@pytest.mark.parametrize('fault', ['child_field', 'parent_field', 'parent_resource', 'reverse', 'uncited', 'partial_citation', 'query_scope'])
def test_relation_requires_exact_direction_keys_resource_and_whole_reference(tmp_path, fault):
    c, docs, accepted = fixture()
    value = json.loads(docs['relations']['content_bytes'])
    fk = value['tableSchema']['foreignKeys'][0]
    if fault == 'child_field': fk['columnReference'] = ['Wrong']
    if fault == 'parent_field': fk['reference']['columnReference'] = ['Other']
    if fault == 'parent_resource': fk['reference']['resource'] = 'https://cdn.example/other.csv'
    if fault == 'reverse': value['url'], fk['reference']['resource'] = PARENT, CHILD
    if fault == 'query_scope': fk['reference']['resource'] = PARENT + '?year=2023'
    replace(docs, 'relations', value)
    if fault == 'uncited': accepted['relations'] = []
    if fault == 'partial_citation':
        accepted['relations'] = [{'document_id': 'relations', 'locator': {'kind': 'json-pointer', 'pointer': '/tableSchema/foreignKeys/0/columnReference'}}]
    _, relation = evaluate(c, docs, accepted)
    assert not relation['ok']


def test_known_contradictory_relation_not_hidden_by_uncited_entry(tmp_path):
    c, docs, accepted = fixture()
    value = json.loads(docs['relations']['content_bytes'])
    value['tableSchema']['foreignKeys'].append({'columnReference': ['Type'], 'reference': {'resource': PARENT, 'columnReference': ['Other']}})
    replace(docs, 'relations', value)
    accepted['relations'] = [{'document_id': 'relations', 'locator': {'kind': 'json-pointer', 'pointer': '/tableSchema/foreignKeys/0'}}]
    _, relation = evaluate(c, docs, accepted)
    assert relation['issues'][0]['code'] == 'LOOKUP_RELATION_CONFLICT'


@pytest.mark.parametrize('fault', ['true', 'duplicate', 'absent', 'inherited'])
def test_optional_keys_need_unambiguous_explicit_nullable_column_definitions(tmp_path, fault):
    c, docs, accepted = fixture()
    c['resources'][0]['lookups'][0]['allow_blank'] = True
    assert evaluate(c, docs, accepted)[1]['ok']
    value = json.loads(docs['relations']['content_bytes'])
    if fault == 'true': value['tableSchema']['columns'][0]['required'] = True
    if fault == 'duplicate': value['tableSchema']['columns'].append({'name': 'Type', 'required': True})
    if fault == 'absent': value['tableSchema']['columns'] = []
    if fault == 'inherited': value['tableSchema']['columns'][0].pop('required')
    replace(docs, 'relations', value)
    assert not evaluate(c, docs, accepted)[1]['ok']


def test_foreign_key_does_not_authorize_unmatched_nonblank_rows(tmp_path):
    c, docs, accepted = fixture()
    c['resources'][0]['lookups'][0]['on_missing'] = 'preserve_unknown'
    assert evaluate(c, docs, accepted)[1]['issues'][0]['code'] == 'LOOKUP_MISSING_POLICY_UNSUPPORTED'


@pytest.mark.parametrize('fault', ['schema_reference', 'nested_context', 'oversize', 'bad_context', 'table_fragment', 'target_fragment'])
def test_unsupported_csvw_shapes_do_not_gain_fallback_authority(tmp_path, fault):
    c, docs, accepted = fixture()
    value = json.loads(docs['relations']['content_bytes'])
    if fault == 'schema_reference':
        value['tableSchema']['foreignKeys'][0]['reference'] = {'schemaReference': 'https://cdn.example/schema', 'columnReference': ['Code']}
    if fault == 'nested_context': value['tableSchema']['@context'] = {'resource': 'https://attacker.example/resource'}
    if fault == 'oversize': value['tableSchema']['foreignKeys'] = [{}] * 65
    if fault == 'bad_context': value['@context'] = {'@vocab': CONTEXT, 'reference': 'https://attacker.example/reference'}
    if fault == 'table_fragment': value['url'] += '#other-table'
    if fault == 'target_fragment': value['tableSchema']['foreignKeys'][0]['reference']['resource'] += '#other-table'
    replace(docs, 'relations', value)
    try:
        grounding, relation = evaluate(c, docs, accepted)
    except MetadataError:
        return
    assert not grounding['ok'] or not relation['ok']


def test_split_coordinate_origins_are_explicit_system_limitation(tmp_path):
    c, _, _ = fixture()
    c['resources'][0]['mapping']['geography']['y_field'] = 'Y'
    with pytest.raises(UnsupportedCapability) as error: geography_resources(c)
    assert error.value.code == 'LOOKUP_COORDINATE_PAIR_SPLIT'


def test_invalid_typed_reference_is_not_silently_ignored(tmp_path):
    c, _, _ = fixture()
    c['resources'][0]['mapping']['severity']['field']['lookup'] = 'missing'
    with pytest.raises(ValidationFailure): _critical_fields(c)


def test_table_group_neighbours_cannot_lend_relations(tmp_path):
    c, docs, accepted = fixture()
    correct = json.loads(docs['relations']['content_bytes'])
    correct.pop('@context')
    neighbour = copy.deepcopy(correct)
    neighbour['url'] = 'https://cdn.example/other.csv'
    wrong = copy.deepcopy(correct)
    wrong['tableSchema']['foreignKeys'][0]['reference']['columnReference'] = ['Wrong']
    replace(docs, 'relations', {'@context': CONTEXT, 'tables': [wrong, neighbour]})
    _, relation = evaluate(c, docs, accepted)
    assert not relation['ok']
    replace(docs, 'relations', {'@context': CONTEXT, 'tables': [correct, neighbour]})
    _, relation = evaluate(c, docs, accepted)
    assert relation['ok']
    assert relation['decisions'][0]['evidence'][0]['locator']['pointer'] == '/tables/0/tableSchema/foreignKeys/0'


def test_composite_key_order_is_not_normalized(tmp_path):
    c, docs, accepted = fixture()
    c['resources'][0]['lookups'][0]['fields'] = ['Type', 'Part']
    c['lookup_tables'][0]['key'] = ['Code', 'Part']
    value = json.loads(docs['relations']['content_bytes'])
    value['tableSchema']['foreignKeys'][0] = {'columnReference': ['Type', 'Part'],
        'reference': {'resource': PARENT, 'columnReference': ['Code', 'Part']}}
    replace(docs, 'relations', value)
    assert evaluate(c, docs, accepted)[1]['ok']
    value['tableSchema']['foreignKeys'][0]['reference']['columnReference'].reverse()
    replace(docs, 'relations', value)
    assert evaluate(c, docs, accepted)[1]['issues'][0]['code'] == 'LOOKUP_RELATION_CONFLICT'


def test_relative_csvw_resource_reference_uses_document_base_without_network(tmp_path):
    c, docs, accepted = fixture()
    value = json.loads(docs['relations']['content_bytes'])
    value['url'] = 'events.csv'
    value['tableSchema']['foreignKeys'][0]['reference']['resource'] = 'codes.csv'
    replace(docs, 'relations', value)
    assert evaluate(c, docs, accepted)[1]['ok']


@pytest.mark.parametrize('fault', [None, 'wrong_outcome', 'wrong_label', 'child_only_domain', 'uncited_parent'])
def test_lookup_category_semantics_use_parent_domain_and_original_consumer(tmp_path, fault):
    from arsia_pipeline.category_evidence import review_categories
    c, docs, accepted = fixture()
    mapping = c['resources'][0]['mapping']['severity']
    mapping['categories'] = {'F': {'code': 'fatal', 'label': 'Fatal', 'is_fatal_crash': True}}
    value = json.loads(docs['parent']['content_bytes'])
    value['fields'][1]['domain'] = {'type': 'codedValue', 'codedValues': [{'code': 'F', 'name': 'Fatal'}]}
    replace(docs, 'parent', value)
    accepted['severity'] = [{'document_id': 'parent', 'quote': docs['parent']['text']}]
    if fault == 'wrong_outcome': mapping['categories']['F']['is_fatal_crash'] = False
    if fault == 'wrong_label': mapping['categories']['F']['label'] = 'Injury'
    if fault == 'uncited_parent': accepted['severity'] = [{'document_id': 'child', 'quote': docs['child']['text']}]
    if fault == 'child_only_domain':
        child = json.loads(docs['child']['content_bytes'])
        child['fields'][3]['domain'] = value['fields'][1].pop('domain')
        replace(docs, 'child', child)
        replace(docs, 'parent', value)
        accepted['severity'] = [{'document_id': key, 'quote': docs[key]['text']} for key in ('child', 'parent')]
    graph = build_graph(SOURCE, docs, {'catalogue'})
    grounding = ground_contract(c, docs, accepted, graph=graph)
    result = review_categories(c, graph, grounding, accepted)
    assert result['lookup_field_origins'] == [{'consumer_role': 'crash', 'mapping': 'severity', 'role': 'codes', 'field': 'Class', 'lookup': 'code'}]
    if fault == 'child_only_domain':
        assert result['decisions'][0]['status'] == 'legacy_text_scope'
        assert not any(d['status'] == 'structured_category_bound' for d in result['decisions'])
    elif fault:
        assert not result['ok']
    else:
        assert result['ok']
        assert result['decisions'][0]['evidence'][0]['document_id'] == 'parent'


def test_real_receipts_reach_parent_diagnostics_but_not_admission(tmp_path, monkeypatch):
    from arsia_pipeline import config
    from arsia_pipeline.trusted_qa import _proof
    c, docs, accepted = fixture()
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    (tmp_path / 'sha256').mkdir()
    c['documents'] = []
    for key, doc in docs.items():
        (tmp_path / 'sha256' / doc['sha256']).write_bytes(doc['content_bytes'])
        path = tmp_path / (key + '.json')
        path.write_text(json.dumps({'status': 'fetched', 'sha256': doc['sha256'], 'final_url': doc['url'], 'final_host_official': key == 'catalogue'}))
        c['documents'].append({'document_id': key, 'receipt_path': str(path)})
    c['evidence'] = accepted
    with pytest.raises(NeedsInput) as error: _proof(c, tmp_path)
    assert error.value.code == 'evidence_needed'
    assert error.value.details['lookup_relation_review']['ok']
    assert not error.value.details['lookup_geography_subject_review']['ok']
    assert all(i['code']=='LOOKUP_GEOGRAPHY_SUBJECT_UNGROUNDED' for i in error.value.details['lookup_geography_subject_review']['issues'])
