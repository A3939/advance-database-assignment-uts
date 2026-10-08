import copy
import hashlib
import json
from pathlib import Path

from openpyxl import Workbook
import pytest

from arsia_pipeline.errors import NeedsInput, ValidationFailure
from arsia_pipeline.intake_tools import IntakeTools
from arsia_pipeline.trusted_qa import validate_contract, validate_candidate
from test_canonical_v2 import envelope


def attachment(tmp_path, text, name='dictionary.csv'):
    path = tmp_path / name
    path.write_text(text)
    return {'id': name, 'name': name, 'path': str(path), 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


@pytest.mark.parametrize('text', [
    'name,description\nAlice,Private personal observation\n',
    'name,description\nID,Private personal observation\n',
    'field,description,record\nID,Official source identifier,Private Person\n',
    'field,description\nUNKNOWN,Unknown personal observation\n',
    'field,description\nID,Official source identifier\nID,Second recorded personal row\n',
    'field,label\nID,Private personal observation\n',
    'field,description\nID,Official source identifier\n,Private personal observation\n',
])
def test_dictionary_looking_records_neither_disappear_nor_leak(tmp_path, text):
    c, file, _ = envelope(tmp_path)
    other = attachment(tmp_path, text)
    with pytest.raises(ValidationFailure, match='not assigned a grain'):
        validate_contract(c, [file, other])
    intake = IntakeTools([file, other], tmp_path / 'inspection')
    inspection = intake.inspect_bundle()
    assert 'dictionary_review' not in inspection['resources'][1]['tables'][0]
    assert 'Private' not in json.dumps(inspection)
    with pytest.raises(NeedsInput, match='not an identified dictionary'):
        intake.read_document(other['id'])


def test_all_dictionary_rows_and_same_target_schema_are_required(tmp_path):
    c, file, _ = envelope(tmp_path)
    body = 'field,description\n' + ''.join(f'{name},Definition for {name} source field\n' for name in ['ID','DATE','SEVERITY','DEATHS','INJURED'])
    other = attachment(tmp_path, body + 'PERSON_ID,An unclassified observation\n')
    with pytest.raises(ValidationFailure, match='not assigned a grain'):
        validate_contract(c, [file, other])
    # This field exists, but only in a different, unassigned physical table.
    extra = attachment(tmp_path, 'PERSON_ID,AGE\nPERSON,42\n', name='people.csv')
    tools = IntakeTools([file, other, extra], tmp_path / 'inspection')
    with pytest.raises(NeedsInput, match='not an identified dictionary'):
        tools.read_document(other['id'])


def test_actual_schema_linked_dictionary_has_preserved_classification_receipt(tmp_path):
    c, file, _ = envelope(tmp_path)
    other = attachment(tmp_path, 'field,description\nID,Identifier of each event\nDATE,Date of reported crash\n')
    receipts = []
    assert validate_contract(c, [file, other], table_receipts=receipts)['crash']['file_id'] == file['id']
    dictionary, = [r for r in receipts if r['purpose'] == 'dictionary']
    assert dictionary['row_count'] == 2
    assert dictionary['describes'] == [{'file_sha256': file['sha256'], 'table_id': 'default', 'fields': ['DATE','ID']}]
    assert dictionary['publisher_authority'] is False and dictionary['semantic_admission'] is False
    tools = IntakeTools([file, other], tmp_path / 'inspection')
    inspection = tools.inspect_bundle()
    assert inspection['resources'][1]['tables'][0]['dictionary_review'] == dictionary
    read = tools.read_document(other['id'])
    assert 'Identifier of each event' in read['text']
    assert read['dictionary_review'] == dictionary
    assert read['official'] is False
    # Inspection order and filenames are not classification authority.
    renamed = {**other, 'name': 'other-name.bin'}
    reverse = []
    validate_contract(c, [renamed, file], table_receipts=reverse)
    assert reverse == receipts


def test_dictionary_by_itself_cannot_authorize_document_read(tmp_path):
    file = attachment(tmp_path, 'field,description\nID,Identifier of each event\n')
    tools = IntakeTools([file], tmp_path / 'inspection')
    with pytest.raises(NeedsInput, match='not an identified dictionary'):
        tools.read_document(file['id'])


def test_hidden_dictionary_and_two_sheets_get_distinct_document_ids(tmp_path):
    c, file, _ = envelope(tmp_path)
    book = Workbook()
    book.active.title = 'Fields'
    book.active.append(['field','definition'])
    book.active.append(['ID','Identifier of each event'])
    hidden = book.create_sheet('Dates')
    hidden.sheet_state = 'hidden'
    hidden.append(['field','definition'])
    hidden.append(['DATE','Date of reported crash'])
    path = tmp_path / 'workbook.xlsx'
    book.save(path)
    other = {'id': 'workbook', 'name': path.name, 'path': str(path), 'size': path.stat().st_size,
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    receipts = []
    validate_contract(c, [file, other], table_receipts=receipts)
    assert len([r for r in receipts if r['purpose'] == 'dictionary']) == 2
    tools = IntakeTools([file, other], tmp_path / 'inspection')
    first, second = [tools.read_document(other['id'], table_id=sheet) for sheet in ('Fields','Dates')]
    assert first['document_id'] != second['document_id']
    assert first['sha256'] == second['sha256'] == other['sha256']
    assert tools.read_document(other['id'], table_id='Fields')['text'] == first['text']


def test_candidate_receipt_records_dictionary_rows_without_counting_as_crashes(tmp_path):
    c, file, run = envelope(tmp_path)
    other = attachment(tmp_path, 'field,description\nID,Identifier of each event\n')
    result = validate_candidate(run, c, [file, other], 'code-sha', tmp_path)
    assert result['summary']['crash_count'] == 1
    review = result['admission']['evidence']['table_classification']
    assert {table['purpose'] for table in review['tables']} == {'fact','dictionary'}
    assert next(t for t in review['tables'] if t['purpose']=='dictionary')['row_count'] == 1


def test_forged_inspection_dictionary_claim_is_not_trusted(tmp_path):
    c, file, _ = envelope(tmp_path)
    other = attachment(tmp_path, 'name,description\nID,Private personal observation\n')
    c['table_plan'] = {'tables': [{'file_id': other['id'], 'purpose':'dictionary', 'verified':True}]}
    with pytest.raises(ValidationFailure, match='not assigned a grain'):
        validate_contract(c, [file, other])


@pytest.mark.parametrize('value', [[[1,2],[3,4]], {'records':[[1,2],[3,4]]},
                                  {'description':'Unclassified actual record', 'id': 123},
                                  {'fields':[{'name':'ID'}], 'records':[[1,2],[3,4]]}])
def test_unsupported_json_records_cannot_be_ignored_as_documents(tmp_path, value):
    c, file, _ = envelope(tmp_path)
    other = attachment(tmp_path, json.dumps(value), name='unassigned.json')
    with pytest.raises((NeedsInput,ValidationFailure)):
        validate_contract(c,[file,other])


def test_metadata_only_uploaded_json_gets_an_explicit_document_receipt(tmp_path):
    c, file, _ = envelope(tmp_path)
    other = attachment(tmp_path, json.dumps({'title':'Publisher documentation', 'description':'Official field dictionary notes',
                                             'fields':[{'name':'ID','description':'Identifier of each event'}]}), name='metadata.json')
    receipts = []
    validate_contract(c,[file,other],table_receipts=receipts)
    assert any(r['purpose']=='structured_document' and r['file_sha256']==other['sha256'] for r in receipts)
