import copy
import hashlib
import json
from pathlib import Path

import pytest

from arsia_pipeline.category_evidence import extract_categories, review_categories
from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.evidence_grounding import ground_contract

URL = 'https://data.example.gov.au/arcgis/rest/services/Crashes/FeatureServer/0'


def fixture():
    data = {'id': 0, 'name': 'Crashes', 'fields': [{'name': 'ID'}, {'name': 'DATE'}, {'name': 'SEVERITY'}],
            'drawingInfo': {'renderer': {'type': 'uniqueValue', 'field1': 'SEVERITY', 'uniqueValueInfos': [
                {'value': 'F', 'label': 'Fatal'}, {'value': 'P', 'label': 'Property Damage Only'}, {'value': 'U', 'label': 'Not known'}]}}}
    c = {'source': {'dataset_url': URL}, 'resources': [{'role': 'crash', 'file_id': 'upload', 'grain': 'crash', 'key': ['ID'], 'mapping': {
        'date': {'field': 'DATE'}, 'severity': {'field': 'SEVERITY', 'categories': {
            'F': {'code': 'fatal', 'label': 'Fatal', 'is_fatal_crash': True},
            'P': {'code': 'pdo', 'label': 'Property Damage Only', 'is_fatal_crash': False},
            'U': {'code': 'unknown', 'label': 'Not known', 'is_fatal_crash': None}}}}}]}
    return c, data


def review(c, data, quote=None):
    raw = json.dumps(data).encode()
    docs = {'official': {'url': URL + '?f=pjson', 'content_bytes': raw, 'text': raw.decode()}}
    accepted = {claim: [{'document_id': 'official', 'quote': raw.decode()}] for claim in ('source_identity', 'grain', 'date', 'severity')}
    if quote is not None:
        accepted['severity'][0]['quote'] = quote
    graph = build_graph(URL, docs, {'official'})
    grounding = ground_contract(c, docs, accepted, graph=graph)
    assert grounding['ok'], grounding
    return review_categories(c, graph, grounding, accepted)


def test_source_categories_bind_exact_field_and_preserve_unknown():
    c, data = fixture(); result = review(c, data)
    assert result['ok']
    assert {r['source_code']: r['fatal_flag'] for r in result['decisions']} == {'F': True, 'P': False, 'U': None}
    assert all(r['status'] == 'structured_category_bound' for r in result['decisions'])


@pytest.mark.parametrize('code,flag', [('F', False), ('P', True), ('U', False), ('U', True)])
def test_fatal_or_unknown_flags_cannot_be_rewritten(code, flag):
    c, data = fixture(); c['resources'][0]['mapping']['severity']['categories'][code]['is_fatal_crash'] = flag
    assert any(i['code'] == 'CATEGORY_OUTCOME_CONFLICT' for i in review(c, data)['issues'])


def test_default_symbol_does_not_authorize_new_value():
    c, data = fixture(); data['drawingInfo']['renderer']['defaultLabel'] = 'Other'
    c['resources'][0]['mapping']['severity']['categories']['new'] = {'code': 'other', 'label': 'Other', 'is_fatal_crash': False}
    assert any(i['code'] == 'CATEGORY_CODE_UNGROUNDED' for i in review(c, data)['issues'])


def test_groups_take_specified_precedence_over_legacy_infos():
    c, data = fixture(); renderer = data['drawingInfo']['renderer']
    renderer['uniqueValueGroups'] = [{'classes': [{'label': item['label'], 'values': [[item['value']]]} for item in renderer['uniqueValueInfos']]}]
    renderer['uniqueValueInfos'][0]['label'] = 'Conflicting obsolete renderer fallback'
    assert review(c, data)['ok']
    assert {row['kind'] for row in extract_categories(data)['records']} == {'renderer_group'}


@pytest.mark.parametrize('change', ['field2', 'expression', 'tuple'])
def test_composite_or_expression_renderers_need_a_reviewed_plan(change):
    c, data = fixture(); renderer = data['drawingInfo']['renderer']
    if change == 'field2': renderer['field2'] = 'OTHER'
    elif change == 'expression': renderer['valueExpression'] = '$feature.SEVERITY'
    else: renderer['uniqueValueGroups'] = [{'classes': [{'label': 'Fatal', 'values': [['F', 'x']]}]}]
    assert any(i['code'] == 'CATEGORY_EXPRESSION_UNSUPPORTED' for i in review(c, data)['issues'])


def test_expression_without_field_does_not_fall_back_to_legacy_field_presence():
    c, data = fixture(); renderer = data['drawingInfo']['renderer']; renderer.pop('field1'); renderer['valueExpression'] = '$feature.SEVERITY'
    assert not review(c, data)['ok']


def test_renderer_of_other_field_cannot_authorize_a_code():
    c, data = fixture(); data['drawingInfo']['renderer']['field1'] = 'OTHER'
    result = review(c, data)
    assert result['decisions'][0]['status'] == 'legacy_text_scope'
    assert not any(r['status'] == 'structured_category_bound' for r in result['decisions'])


def test_coded_domain_and_renderer_conflict_cannot_be_hidden_by_citation():
    c, data = fixture(); data['fields'][2]['domain'] = {'type': 'codedValue', 'codedValues': [{'code': 'F', 'name': 'Minor'}]}
    result = review(c, data, quote='Official category Fatal and Property Damage Only; Not known')
    assert any(i['code'] == 'CATEGORY_DEFINITION_CONFLICT' for i in result['issues'])


def test_exact_category_citation_and_native_label_are_required():
    c, data = fixture()
    assert any(i['code'] == 'CATEGORY_CITATION_REQUIRED' for i in review(c, data, quote='SEVERITY field name only')['issues'])
    c['resources'][0]['mapping']['severity']['categories']['P']['label'] = 'No damage'
    assert any(i['code'] == 'CATEGORY_LABEL_MISMATCH' for i in review(c, data)['issues'])


def test_labels_are_not_cross_source_standard_severity_authority():
    c, data = fixture(); c['resources'][0]['mapping']['severity']['categories']['F']['standard_code'] = 'uniform_fatal'
    assert any(i['code'] == 'CATEGORY_HARMONIZATION_UNPROVEN' for i in review(c, data)['issues'])


def test_different_source_categories_cannot_collapse_into_one_canonical_code():
    c, data = fixture()
    c['resources'][0]['mapping']['severity']['categories']['P']['code'] = 'fatal'
    assert any(i['code'] == 'CATEGORY_CODE_COLLISION' for i in review(c, data)['issues'])


def test_same_meaning_source_aliases_may_share_a_canonical_code():
    c, data = fixture()
    data['drawingInfo']['renderer']['uniqueValueInfos'].append({'value': 'F2', 'label': 'Fatal'})
    c['resources'][0]['mapping']['severity']['categories']['F2'] = copy.deepcopy(c['resources'][0]['mapping']['severity']['categories']['F'])
    assert review(c, data)['ok']


def test_receipt_and_exact_locator_reach_the_trusted_category_gate(tmp_path, monkeypatch):
    """A synthetic publisher receipt exercises _proof, not real-source admission."""
    from arsia_pipeline import config
    from arsia_pipeline.errors import NeedsInput
    from arsia_pipeline.evidence_references import reference
    from arsia_pipeline.trusted_qa import _proof
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    c, data = fixture(); raw = json.dumps(data).encode(); sha = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'sha256').mkdir(); (tmp_path / 'sha256' / sha).write_bytes(raw)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'status': 'fetched', 'sha256': sha, 'final_url': URL + '?f=pjson', 'final_host_official': True}))
    c['documents'] = [{'document_id': 'official', 'receipt_path': str(receipt)}]
    root = reference(raw, sha, 'official', {'kind': 'json-pointer', 'pointer': ''})
    c['evidence'] = {claim: [root] for claim in ('source_identity', 'grain', 'date', 'severity', 'coverage_update')}
    result = _proof(c, tmp_path)
    assert result['category_review']['ok']
    assert len(result['category_review']['decisions']) == 3
    c['evidence']['severity'] = [reference(raw, sha, 'official', {'kind': 'json-pointer', 'pointer': '/fields/2'})]
    with pytest.raises(NeedsInput) as failure:
        _proof(c, tmp_path)
    assert {issue['code'] for issue in failure.value.details['category_review']['issues']} == {'CATEGORY_CITATION_REQUIRED'}


def test_unknown_named_outcome_stays_unknown():
    c, data = fixture(); data['drawingInfo']['renderer']['uniqueValueInfos'][2]['label'] = 'Awaiting review'
    c['resources'][0]['mapping']['severity']['categories']['U']['label'] = 'Awaiting review'
    assert review(c, data)['ok']


@pytest.mark.parametrize('evidence_id,expected', [('tas-layer', {'Fatal', 'Serious', 'Minor', 'First Aid', 'Property Damage Only', 'Not known'}),
                                                ('wa-crashmap', {'Fatal', 'Hospital', 'Medical', 'PDO Major', 'PDO minor'})])
def test_frozen_actual_provider_metadata(evidence_id, expected):
    root = Path(__file__).resolve().parents[1] / 'arsia_pipeline/knowledge'
    entry = json.loads((root / 'catalog.json').read_text())['evidence_index'][evidence_id]
    raw = (root / entry['object']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == entry['sha256']
    result = extract_categories(json.loads(raw))
    assert not result['issues']
    assert {item['label'] for item in result['records']} == expected
    assert {item['field'] for item in result['records']} == {'SEVERITY'}
