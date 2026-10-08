import copy
import hashlib
import json

import pytest

from arsia_pipeline.canonical import ContractError, count_value
from arsia_pipeline.count_semantics import expression, review_count_operations
from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.evidence_grounding import ground_contract

URL = 'https://data.example.gov.au/d/abcd-1234'
DOC = 'https://data.example.gov.au/api/views/abcd-1234.json'


def fixture(statement='Total casualties = deaths + injured'):
    value = {'id': 'abcd-1234', 'columns': [
        {'fieldName': 'id', 'name': 'ID'}, {'fieldName': 'date', 'name': 'Date'},
        {'fieldName': 'deaths', 'name': 'Deaths', 'description': 'Number of deceased persons'},
        {'fieldName': 'injured', 'name': 'Injured', 'description': 'Number of injured persons'},
        {'fieldName': 'total', 'name': 'Total', 'description': statement}]}
    raw = json.dumps(value).encode()
    docs = {'official': {'url': DOC, 'content_bytes': raw, 'text': raw.decode(), 'sha256': hashlib.sha256(raw).hexdigest()}}
    contract = {'source': {'dataset_url': URL}, 'resources': [{'role': 'crash', 'file_id': 'upload', 'grain': 'crash', 'key': ['id'],
        'mapping': {'date': {'field': 'date'}, 'casualties': {'sum_fields': ['deaths', 'injured']}}}]}
    accepted = {claim: [{'document_id': 'official', 'quote': raw.decode()}] for claim in ('source_identity', 'grain', 'date', 'counts', 'coverage_update')}
    return contract, docs, accepted


def review(contract, docs, accepted):
    graph = build_graph(URL, docs, {'official'})
    grounding = ground_contract(contract, docs, accepted, graph=graph)
    assert grounding['ok'], grounding
    return review_count_operations(contract, docs, grounding, accepted, graph)


def test_explicit_official_sum_produces_a_scoped_operator_claim():
    c, docs, accepted = fixture()
    result = review(c, docs, accepted)
    assert result['ok'] and len(result['decisions']) == 1
    claim = result['decisions'][0]
    assert claim['official_operands'] == ['deaths', 'injured']
    assert claim['evidence'][0]['schema_pointer'] == '/columns/4/description'
    assert count_value({'deaths': '2', 'injured': '3'}, c['resources'][0]['mapping']['casualties'], {}) == 5


@pytest.mark.parametrize('statement', ['Both deaths and injured are documented fields.',
    'Total casualties is not deaths plus injured.', 'Example only: Total casualties = deaths + injured',
    'Total casualties = deaths + injured; do not use for totals', 'Total casualties = deaths * 2 + injured',
    'Total casualties = deaths + injured (different populations)', 'Total casualties = deaths + injured < 5'])
def test_field_existence_negations_examples_or_qualifiers_are_not_sum_authority(statement):
    c, docs, accepted = fixture(statement)
    c['definitions'] = {'sum_disjoint': True, 'sum_units_match': True, 'sum_scope_match': True}
    result = review(c, docs, accepted)
    assert not result['ok']
    assert result['issues'][0]['code'] == 'COUNT_SUM_UNGROUNDED'


def test_explicit_different_operands_conflict_even_if_citation_is_omitted():
    c, docs, accepted = fixture('Total casualties = deaths + injured + other')
    accepted['counts'][0]['quote'] = 'Number of deceased persons Number of injured persons'
    result = review(c, docs, accepted)
    assert result['issues'][0]['code'] == 'COUNT_SUM_DEFINITION_CONFLICT'


def test_correct_equation_needs_an_actual_citation():
    c, docs, accepted = fixture()
    accepted['counts'][0]['quote'] = 'Number of deceased persons Number of injured persons'
    assert review(c, docs, accepted)['issues'][0]['code'] == 'COUNT_SUM_UNGROUNDED'


def test_nested_neighbour_schema_cannot_lend_its_sum():
    c, docs, accepted = fixture('No additive definition')
    value = json.loads(docs['official']['content_bytes'])
    value['other_resource'] = {'fields': [{'name': 'total', 'description': 'Total casualties = deaths + injured'}]}
    raw = json.dumps(value).encode()
    docs['official'].update(content_bytes=raw, text=raw.decode())
    accepted['counts'][0]['quote'] = raw.decode()
    assert not review(c, docs, accepted)['ok']


def test_two_aliases_of_the_same_count_are_overlap():
    c, docs, accepted = fixture('Total casualties = deaths + Deaths')
    c['resources'][0]['mapping']['casualties']['sum_fields'] = ['deaths', 'Deaths']
    assert review(c, docs, accepted)['issues'][0]['code'] == 'COUNT_OPERANDS_OVERLAP'


@pytest.mark.parametrize('form', ['duplicate_field', 'second_property'])
def test_repeated_official_definitions_cannot_hide_a_conflict(form):
    c, docs, accepted = fixture()
    value = json.loads(docs['official']['content_bytes'])
    if form == 'duplicate_field':
        value['columns'].insert(0, {'fieldName': 'total', 'description': 'Total casualties = deaths + other'})
    else:
        value['columns'][-1]['definition'] = 'Total casualties = deaths + other'
    raw = json.dumps(value).encode(); docs['official'].update(content_bytes=raw, text=raw.decode())
    accepted['counts'][0]['quote'] = raw.decode()
    assert review(c, docs, accepted)['issues'][0]['code'] == 'COUNT_SUM_DEFINITION_CONFLICT'


def test_fatal_crash_formula_cannot_authorize_a_person_count():
    c, docs, accepted = fixture('Total fatal crashes = deaths + injured')
    assert not review(c, docs, accepted)['ok']


@pytest.mark.parametrize('fields', [['n', 'n'], ['', 'n'], [None, 'n'], ['n'] * 33])
def test_arithmetic_refuses_duplicate_or_invalid_operands(fields):
    with pytest.raises(ContractError):
        count_value({'n': '1'}, {'sum_fields': fields}, {})


def test_computed_total_is_bounded_and_not_reinterpreted_as_a_raw_missing_marker():
    with pytest.raises(ContractError, match='range'):
        count_value({'a': '2147483647', 'b': '1'}, {'sum_fields': ['a', 'b']}, {})
    assert count_value({'a': '1', 'b': '2'}, {'sum_fields': ['a', 'b']}, {'null_values': [3]}) == 3
    assert count_value({'a': '1', 'b': ''}, {'sum_fields': ['a', 'b']}, {}) is None
    assert count_value({'a': '0', 'b': '0'}, {'sum_fields': ['a', 'b']}, {}) == 0


def test_official_equation_grammar_preserves_spaces_in_fields_and_order():
    assert expression('Total number of casualties: "No. killed" + "No. injured".', 'casualties') == ['No. killed', 'No. injured']
    c, docs, accepted = fixture('Total casualties = injured + deaths')
    assert review(c, docs, accepted)['ok']


def test_one_field_sum_keeps_the_direct_projection_semantics():
    c, docs, accepted = fixture('No multi-field total is documented')
    c['resources'][0]['mapping'].pop('casualties')
    c['resources'][0]['mapping']['fatalities'] = {'sum_fields': ['deaths']}
    result = review(c, docs, accepted)
    assert result['ok'] and result['decisions'][0]['claim_type'] == 'identity_count_projection'


def test_real_receipts_and_locators_reach_count_gate(tmp_path, monkeypatch):
    from arsia_pipeline import config
    from arsia_pipeline.errors import NeedsInput
    from arsia_pipeline.evidence_references import reference
    from arsia_pipeline.trusted_qa import _proof
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    c, docs, accepted = fixture()
    doc = docs['official']; raw = doc['content_bytes']; sha = doc['sha256']
    (tmp_path / 'sha256').mkdir(); (tmp_path / 'sha256' / sha).write_bytes(raw)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'status': 'fetched', 'sha256': sha, 'final_url': DOC, 'final_host_official': True}))
    c['documents'] = [{'document_id': 'official', 'receipt_path': str(receipt)}]
    c['evidence'] = accepted
    c['evidence']['counts'] = [reference(raw, sha, 'official', {'kind': 'json-pointer', 'pointer': '/columns/' + str(i)}) for i in (2, 3, 4)]
    assert _proof(c, tmp_path)['count_operation_review']['ok']
    c['evidence']['counts'].pop()
    with pytest.raises(NeedsInput) as failure:
        _proof(c, tmp_path)
    assert failure.value.details['count_operation_review']['issues'][0]['code'] == 'COUNT_SUM_UNGROUNDED'
