import copy

import pytest

from arsia_pipeline.casualty_review import review_casualty_scope


def fixture():
    c = {"resources": [
        {"role": "crash", "grain": "crash", "key": ["EVENT_ID"], "mapping": {"casualties": {"field": "TOTAL"}}},
        {"role": "people", "grain": "casualty", "key": ["EVENT_ID", "PERSON_NO"], "mapping": {}}],
        "relations": [{"child": "people", "parent": "crash", "fields": ["EVENT_ID"]}], "definitions": {}, "evidence": {}}
    return c, {}, {"connected_documents": ["official"]}


def add_scope(c, docs, complete, quote):
    c["definitions"]["casualty_table_complete"] = complete
    c["evidence"]["casualty_scope"] = [{"resource_role": "people", "document_id": "official", "quote": quote}]
    docs["official"] = {"text": quote, "url": "https://data.example.gov.au/dictionary"}


def test_child_table_and_parent_total_cannot_silently_skip_applicability():
    c, docs, g = fixture()
    result = review_casualty_scope(c, docs, g)
    assert not result["ok"] and result["issues"][0]["code"] == "CASUALTY_SCOPE_REQUIRED"
    assert "declared_casualties" in result["issues"][0]["next_action"]


def test_explicit_source_declared_parent_count_uses_existing_equality_qa():
    c, docs, g = fixture()
    c["resources"][0]["mapping"]["declared_casualties"] = {"field": "TOTAL"}
    assert review_casualty_scope(c, docs, g)["ok"]


@pytest.mark.parametrize("complete,quote", [(True, "The complete casualty register is identified by EVENT_ID and PERSON_NO.")])
def test_complete_or_partial_scope_requires_exact_resource_bound_official_statement(complete, quote):
    c, docs, g = fixture()
    add_scope(c, docs, complete, quote)
    result = review_casualty_scope(c, docs, g)
    assert result["ok"] and result["decisions"][0]["complete"] is complete


@pytest.mark.parametrize("quote", [
    "The casualty table is keyed by EVENT_ID and PERSON_NO. Fatality means only deaths within 30 days.",
    "The casualty table keyed by EVENT_ID and PERSON_NO includes only treated casualties."])
def test_partial_scope_requires_clarification_not_a_keyword_decision(quote):
    c, docs, g = fixture()
    add_scope(c, docs, False, quote)
    result = review_casualty_scope(c, docs, g)
    assert not result["ok"] and not result["decisions"]


def test_broad_catalogue_other_package_cannot_prove_complete_scope():
    import json
    c, docs, g = fixture()
    quote = "The complete casualty register is identified by EVENT_ID and PERSON_NO."
    add_scope(c, docs, True, quote)
    docs["official"]["text"] = json.dumps({"result": {"results": [
        {"name": "actual", "notes": "Actual event source"}, {"name": "unrelated", "notes": quote}]}})
    assert not review_casualty_scope(c, docs, g)["ok"]


def test_another_sentence_about_complete_register_cannot_bind_keys():
    c, docs, g = fixture()
    add_scope(c, docs, True, "The casualty table is keyed by EVENT_ID and PERSON_NO. The other complete casualty register has different keys.")
    assert not review_casualty_scope(c, docs, g)["ok"]


@pytest.mark.parametrize("change", ["free_text", "unconnected", "wrong_key", "wrong_resource", "inexact_quote", "non_boolean", "conflicting_complete"])
def test_partial_claim_cannot_bypass_with_unverified_or_contradictory_scope(change):
    c, docs, g = fixture()
    quote = "The casualty table keyed by EVENT_ID and PERSON_NO includes only treated casualties."
    add_scope(c, docs, False, quote)
    if change == "free_text": c["evidence"] = {}; c["definitions"]["reason"] = quote
    if change == "unconnected": g["connected_documents"] = []
    if change == "wrong_key": c["resources"][1]["key"] = ["UNRELATED_ID"]
    if change == "wrong_resource": c["evidence"]["casualty_scope"][0]["resource_role"] = "unrelated"
    if change == "inexact_quote": docs["official"]["text"] = "A different official statement."
    if change == "non_boolean": c["definitions"]["casualty_table_complete"] = "false"
    if change == "conflicting_complete":
        docs["other"] = {"text": "The complete casualty register uses EVENT_ID and PERSON_NO."}
        g["connected_documents"].append("other")
    assert not review_casualty_scope(c, docs, g)["ok"]


def test_no_child_register_or_no_parent_count_has_no_new_requirement():
    c, docs, g = fixture()
    c["relations"] = []
    assert review_casualty_scope(c, docs, g)["ok"]
    c, docs, g = fixture()
    del c["resources"][0]["mapping"]["casualties"]
    assert review_casualty_scope(c, docs, g)["ok"]


@pytest.mark.parametrize('quote', [
    'This is not a complete casualty register identified by EVENT_ID and PERSON_NO.',
    'If approved, a complete casualty register would use EVENT_ID and PERSON_NO.',
    'The complete casualty register is identified by EVENT_ID and PERSON_NO only if all records are supplied.',
    'The complete casualty register is identified by EVENT_ID and PERSON_NO and UNRELATED_ID.',
    'The complete casualty register is identified by EVENT_ID and EVENT_ID and PERSON_NO.',
    'Example: The complete casualty register uses EVENT_ID and PERSON_NO.',
    'The complete casualty register is identified by EVENT_ID and PERSON_NO; completeness is not guaranteed.',
])
def test_whole_affirmative_declaration_not_mentions_or_hypotheses(quote):
    c, docs, g = fixture()
    add_scope(c, docs, True, quote)
    assert not review_casualty_scope(c, docs, g)['ok']


@pytest.mark.parametrize('quote', [
    'The complete casualty register uses PERSON_NO and EVENT_ID.',
    'The casualty table keyed by EVENT_ID and PERSON_NO contains all reported casualties.',
    'The casualty dataset identified by EVENT_ID, PERSON_NO is complete.',
])
def test_supported_complete_scope_forms_keep_exact_keys(quote):
    c, docs, g = fixture()
    add_scope(c, docs, True, quote)
    assert review_casualty_scope(c, docs, g)['ok']


@pytest.mark.parametrize('partial', [
    'The casualty table keyed by EVENT_ID and PERSON_NO contains only treated casualties.',
    'The casualty dataset identified by EVENT_ID and PERSON_NO is not complete.',
    'The casualty register using EVENT_ID and PERSON_NO is a sample of reported casualties.',
])
def test_uncited_partial_source_declaration_conflicts_with_complete_claim(partial):
    c, docs, g = fixture()
    add_scope(c, docs, True, 'The complete casualty register uses EVENT_ID and PERSON_NO.')
    docs['other'] = {'url': 'https://data.example.gov.au/dictionary-2', 'text': partial}
    g['connected_documents'].append('other')
    result = review_casualty_scope(c, docs, g)
    assert not result['ok'] and result['issues'][0]['code'] == 'CASUALTY_SCOPE_CONFLICT'
    assert len(result['issues'][0]['declarations']) == 2
    # The same declaration for another key is not this table's contradiction.
    docs['other']['text'] = partial.replace('PERSON_NO', 'OTHER_PERSON_ID')
    assert review_casualty_scope(c, docs, g)['ok']


def test_verified_partial_scope_is_system_gap_not_missing_dictionary():
    from arsia_pipeline.capability_preflight import exception_blockers, requires_system_change
    from arsia_pipeline.errors import NeedsInput
    c, docs, g = fixture()
    add_scope(c, docs, False, 'The casualty table keyed by EVENT_ID and PERSON_NO contains only treated casualties.')
    result = review_casualty_scope(c, docs, g)
    assert not result['ok'] and result['issues'][0]['code'] == 'CASUALTY_PARTIAL_SCOPE_UNSUPPORTED'
    blockers = exception_blockers(NeedsInput('Scope', [], {'casualty_scope_review': result}))
    assert requires_system_change({'blockers': blockers})
    assert blockers[0]['responsible_party'] == 'system'


def structured_scope(tmp_path, monkeypatch, *, total=1, declaration=None):
    """Synthetic official receipt, actual uploaded CSVs; no mocked QA."""
    import hashlib
    import json
    from arsia_pipeline import config
    from arsia_pipeline.evidence_references import reference
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    c, _, _ = fixture()
    declaration = declaration or 'The complete casualty register uses EVENT_ID and PERSON_NO.'
    c.update(contract_version='canonical-v2',
             source={'source_id': 'scope_fixture', 'title': 'Synthetic scope fixture', 'publisher': 'Test publisher', 'licence': 'Synthetic fixture',
                     'jurisdiction': ['ACT'], 'dataset_url': 'https://data.example.gov.au/d/abcd-1234',
                     'coverage': {'from': '2024-01-01', 'to': '2024-12-31'}},
             update={'mode': 'snapshot'}, definitions={'casualty_table_complete': True})
    files = []
    for resource, body in zip(c['resources'], ['EVENT_ID,DATE,TOTAL\n001,2024-01-01,' + str(total) + '\n',
                                              'EVENT_ID,PERSON_NO\n001,1\n']):
        role = resource['role']; path = tmp_path / (role + '.csv'); path.write_text(body)
        resource.update(file_id=role, table={'format': 'csv'})
        if role == 'crash':
            resource['mapping']['date'] = {'field': 'DATE', 'formats': ['%Y-%m-%d'], 'precision': 'day'}
        files.append({'id': role, 'name': path.name, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size})
    value = {'id': 'abcd-1234', 'description': declaration, 'columns': [
        {'fieldName': field, 'name': field} for field in ['EVENT_ID', 'PERSON_NO', 'DATE', 'TOTAL']]}
    value['columns'][-1]['description'] = 'Number of casualties'
    raw = json.dumps(value).encode(); sha = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'sha256').mkdir(); (tmp_path / 'sha256' / sha).write_bytes(raw)
    url = 'https://data.example.gov.au/api/views/abcd-1234.json'
    receipt = tmp_path / 'receipt.json'; receipt.write_text(json.dumps({'status': 'fetched', 'sha256': sha, 'final_url': url, 'final_host_official': True}))
    doc = {'url': url, 'sha256': sha, 'text': raw.decode(), 'content_bytes': raw}
    c['documents'] = [{'document_id': 'official', 'receipt_path': str(receipt)}]
    c['evidence'] = {claim: [{'document_id': 'official', 'quote': raw.decode()}]
                     for claim in ['source_identity', 'grain', 'coverage_update', 'date', 'counts', 'relations']}
    c['evidence']['casualty_scope'] = [dict(reference(raw, sha, 'official', {'kind': 'json-pointer', 'pointer': '/description'}), resource_role='people')]
    from source_binding_fixture import add_reference
    export_url='https://data.example.gov.au/api/views/abcd-1234/rows.csv?accessType=DOWNLOAD'
    # Two explicitly synthetic historical exports exercise scope QA for both
    # grains. They are fixture receipts, never real official-source evidence.
    first=add_reference(files,tmp_path,export_url,index=0)
    add_reference(files,tmp_path,export_url,index=1)
    files.append(first)
    return c, files, {'official': doc}


def test_structured_scope_locator_reaches_actual_proof(tmp_path, monkeypatch):
    from arsia_pipeline.trusted_qa import _proof
    c, files, _ = structured_scope(tmp_path, monkeypatch)
    proof = _proof(c, tmp_path, files)['casualty_scope_review']
    assert proof['ok'] and proof['decisions'][0]['complete'] is True
    assert proof['decisions'][0]['evidence'][0]['locator']['pointer'] == '/description'


@pytest.mark.parametrize('tamper', ['document_hash', 'value_hash', 'quote', 'neighbour_location'])
def test_structured_scope_never_falls_back_from_bad_locator(tmp_path, monkeypatch, tamper):
    from arsia_pipeline.trusted_qa import _proof
    from arsia_pipeline.errors import NeedsInput
    c, files, _ = structured_scope(tmp_path, monkeypatch)
    e = c['evidence']['casualty_scope'][0]
    if tamper == 'document_hash': e['document_sha256'] = '0' * 64
    if tamper == 'value_hash': e['value_sha256'] = '0' * 64
    if tamper == 'quote': e['quote'] += ' changed'
    if tamper == 'neighbour_location': e['locator']['pointer'] = '/columns/0/name'
    with pytest.raises(NeedsInput) as failure:
        _proof(c, tmp_path, files)
    assert failure.value.details['casualty_scope_review']['issues'][0]['code'] == 'CASUALTY_SCOPE_REQUIRED'


def test_nested_json_neighbour_cannot_authorize_scope(tmp_path, monkeypatch):
    import hashlib
    import json
    from arsia_pipeline.evidence_references import reference
    c, _, docs = structured_scope(tmp_path, monkeypatch)
    value = json.loads(docs['official']['content_bytes'])
    value['neighbour'] = {'description': value.pop('description')}
    raw = json.dumps(value).encode(); sha = hashlib.sha256(raw).hexdigest()
    docs['official'].update(content_bytes=raw, text=raw.decode(), sha256=sha)
    c['evidence']['casualty_scope'] = [dict(reference(raw, sha, 'official', {'kind': 'json-pointer', 'pointer': '/neighbour/description'}), resource_role='people')]
    result = review_casualty_scope(c, docs, {'connected_documents': ['official']})
    assert not result['ok']


def test_actual_proof_partial_scope_has_no_user_question(tmp_path, monkeypatch):
    from arsia_pipeline.trusted_qa import _proof
    from arsia_pipeline.capability_preflight import requires_system_change, preflight_contract
    from arsia_pipeline.errors import NeedsInput
    c, files, _ = structured_scope(tmp_path, monkeypatch, declaration='The casualty table keyed by EVENT_ID and PERSON_NO contains only treated casualties.')
    c['definitions']['casualty_table_complete'] = False
    with pytest.raises(NeedsInput) as failure:
        _proof(c, tmp_path, files)
    assert failure.value.questions == []
    assert requires_system_change(failure.value.details)
    assert requires_system_change(preflight_contract(c, files, tmp_path))
