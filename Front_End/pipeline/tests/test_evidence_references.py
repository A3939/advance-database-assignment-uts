import copy
import hashlib
import io
import json
from pathlib import Path

import pytest

from arsia_pipeline import config
from arsia_pipeline.agent import safe
from arsia_pipeline.errors import NeedsInput
from arsia_pipeline.evidence_references import reference, assert_documentation_locator
from arsia_pipeline.intake_tools import IntakeTools
from arsia_pipeline.metadata_extractors import MetadataError, extract, resolve_locator
from arsia_pipeline.trusted_qa import _proof


def registered(tmp_path, raw, url):
    sha = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'sha256').mkdir(exist_ok=True)
    path = tmp_path / 'sha256' / sha
    path.write_bytes(raw)
    receipt = tmp_path / (sha + '.json')
    receipt.write_text(json.dumps({'status': 'fetched', 'sha256': sha, 'final_url': url, 'final_host_official': True}))
    return {'id': 'source-'+sha, 'name': 'dictionary', 'path': str(path), 'size': len(raw), 'sha256': sha,
            'receipt_path': str(receipt), 'role': 'public_evidence', 'evidence_url': url}


def setup_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    url = 'https://data.example.gov.au/api/views/abcd-1234.json'
    data = {'id': 'abcd-1234', 'description': 'Official reported events from 2024.',
            'columns': [{'fieldName': 'ID', 'description': 'Unique event identifier'},
                        {'fieldName': 'DATE', 'description': 'Occurrence date'},
                        {'fieldName': 'OTHER_DATE', 'description': 'Unrelated date'}]}
    file = registered(tmp_path, json.dumps(data).encode(), url)
    tools = IntakeTools([file], tmp_path / 'tools')
    documents = None
    entries = {}
    for claim, pointer in [('source_identity', '/id'), ('grain', '/columns/0'), ('date', '/columns/1'), ('coverage_update', '/description')]:
        result = tools.read_document(file['id'], locator={'kind': 'json-pointer', 'pointer': pointer})
        entries[claim] = [result['reference']]
        documents = result['__documents']
    value = {'source': {'dataset_url': 'https://data.example.gov.au/d/abcd-1234'}, 'resources': [
        {'role': 'crash', 'file_id': 'upload', 'grain': 'crash', 'key': ['ID'], 'mapping': {'date': {'field': 'DATE'}}}],
        'documents': documents, 'evidence': entries}
    return value, file


def test_tool_reference_reaches_real_proof_without_long_quote(tmp_path, monkeypatch):
    value, file = setup_contract(tmp_path, monkeypatch)
    for entries in value['evidence'].values():
        entries[0].pop('quote')
    proof = _proof(value, tmp_path)
    assert proof['grounding']['ok']
    assert proof['date'][0]['document_sha256'] == file['sha256']
    date_binding = next(b for b in proof['grounding']['field_bindings'] if b['field'] == 'DATE')
    assert date_binding['evidence'][0]['schema_pointer'] == '/columns/1'


@pytest.mark.parametrize('mutation,reason', [
    ('wrong_hash', 'EVIDENCE_HASH_MISMATCH'), ('missing', 'EVIDENCE_LOCATOR_INVALID'),
    ('changed_value', 'EVIDENCE_VALUE_MISMATCH'), ('forged_quote', 'EVIDENCE_VALUE_MISMATCH'),
])
def test_bad_pinned_reference_cannot_use_valid_fallback_quote(tmp_path, monkeypatch, mutation, reason):
    value, _ = setup_contract(tmp_path, monkeypatch)
    entry = value['evidence']['date'][0]
    if mutation == 'wrong_hash': entry['document_sha256'] = '0' * 64
    elif mutation == 'missing': entry['locator']['pointer'] = '/columns/100'
    elif mutation == 'changed_value': entry['value_sha256'] = 'f' * 64
    else: entry['quote'] = 'Fabricated official meaning'
    with pytest.raises(NeedsInput) as exc:
        _proof(value, tmp_path)
    assert reason in {r['reason'] for r in exc.value.details['rejected_evidence']}


def test_existing_locator_to_different_field_does_not_borrow_correct_schema(tmp_path, monkeypatch):
    value, file = setup_contract(tmp_path, monkeypatch)
    value['evidence']['date'] = [reference(Path(file['path']).read_bytes(), file['sha256'],
        value['documents'][0]['document_id'], {'kind': 'json-pointer', 'pointer': '/columns/2'})]
    with pytest.raises(NeedsInput) as exc:
        _proof(value, tmp_path)
    assert any(i['code'] == 'MAPPED_FIELD_UNGROUNDED' and i.get('field') == 'DATE' for i in exc.value.details['grounding']['issues'])


def test_xml_expanded_segments_survive_model_safe_projection_and_hash_check():
    raw = b'<r xmlns:g="https://example.gov.au/schema"><g:definition>ID means event</g:definition></r>'
    sha = hashlib.sha256(raw).hexdigest()
    locator = {'kind': 'xml-expanded-path', 'segments': [['r', 0], ['{https://example.gov.au/schema}definition', 0]]}
    item = safe(reference(raw, sha, 'official', locator))
    assert item['locator'] == locator
    assert resolve_locator(raw, sha, item['locator']) == 'ID means event'
    changed = copy.deepcopy(locator); changed['segments'][1][0] = '{https://wrong.example/}definition'
    with pytest.raises(MetadataError): resolve_locator(raw, sha, changed)


def pdf_bytes(lines):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = PdfWriter()
    for text in lines:
        page = writer.add_blank_page(500, 600)
        font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream = DecodedStreamObject(); stream.set_data(('BT /F1 12 Tf 20 500 Td ('+text+') Tj ET').encode())
        page[NameObject('/Contents')] = stream
    buffer = io.BytesIO(); writer.write(buffer)
    return buffer.getvalue()


def test_pdf_reference_crosses_pages_and_preserves_offsets(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    lines = ['ID identifies an accident.', 'DATE is its occurrence date.']
    raw = pdf_bytes(lines)
    file = registered(tmp_path, raw, 'https://data.example.gov.au/files/manual.pdf')
    text = '\n\n'.join(lines)
    locator = {'kind':'pdf-text-range', 'page_from':1, 'page_to':2, 'start':0, 'end':len(text)}
    output = IntakeTools([file], tmp_path/'tools').read_document(file['id'], locator=locator)
    assert output['reference']['quote'] == text
    bad = {**locator, 'end':len(text)+1}
    with pytest.raises(MetadataError):resolve_locator(raw, file['sha256'], bad)
    with pytest.raises(MetadataError):resolve_locator(raw+b' ', file['sha256'], locator)


@pytest.mark.parametrize('pointer', ['', '/columns/0/cachedContents', '/features/0/properties/Name'])
def test_metadata_reference_does_not_bypass_row_redaction(pointer):
    raw = json.dumps({'columns':[{'name':'ID', 'cachedContents':{'rows':['private value']}}],
                      'features':[{'properties':{'Name':'private name'}}]}).encode()
    with pytest.raises(MetadataError, match='record'):
        assert_documentation_locator(raw, hashlib.sha256(raw).hexdigest(), {'kind':'json-pointer','pointer':pointer})


def test_numeric_exponent_overflow_is_not_finite_json_metadata():
    with pytest.raises(MetadataError) as exc:extract(b'{"value":1e9999}')
    assert exc.value.code == 'METADATA_NONFINITE'
