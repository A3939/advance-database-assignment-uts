import copy
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from arsia_pipeline.errors import ImportCancelled, UnsupportedCapability, ValidationFailure
from arsia_pipeline.lookup_plan import LookupIndex, prepare_lookup, VERSION


def admitted(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text)
    return {'id': name, 'name': name, 'path': str(path), 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture(tmp_path, text='Code,Label,Region\n001,First,N\n1,Second,S\nunused,Unused,N\n'):
    file = admitted(tmp_path, 'parent.csv', text)
    resource = {'role': 'codebook', 'purpose': 'lookup', 'file_id': file['id'], 'table': {}, 'key': ['Code']}
    join = {'child_role': 'crash', 'fields': ['Type'], 'select': ['Label', 'Region'], 'allow_blank': False, 'on_missing': 'error'}
    return resource, [file], join


def code(exc):
    return exc.value.qa[0]['code']


def test_exact_lookup_preserves_cardinality_values_and_physical_lineage(tmp_path):
    resource, files, join = fixture(tmp_path)
    raw_children = [{'ID': 'crash1', 'Type': '001'}, {'ID': 'crash2', 'Type': '001'}, {'ID': 'crash3', 'Type': '1'}]
    saved = copy.deepcopy(raw_children)
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        results = [index.resolve(row) for row in raw_children]
        report = index.receipt()
        assert index.path.stat().st_mode & 0o777 == 0o600
    assert raw_children == saved
    assert len(results) == len(raw_children)
    # Independent literal expectations: no canonical/project or reader oracle.
    assert [row['values'] for row in results] == [{'Label': 'First', 'Region': 'N'}, {'Label': 'First', 'Region': 'N'}, {'Label': 'Second', 'Region': 'S'}]
    assert [row['lineage']['row_locator'] for row in results] == ['csv:1', 'csv:1', 'csv:2']
    assert all(row['lineage']['file_sha256'] == files[0]['sha256'] for row in results)
    assert report['metrics'] == {'parent_rows': 3, 'requests': 3, 'matched': 3, 'unmatched': 0, 'all_blank': 0,
                                  'rejected': 0, 'join_extra_rows': 0, 'used_parent_keys': 2, 'unused_parent_keys': 1, 'max_children_per_parent': 2}
    assert report['admission'] is False and report['complete_parent_scan'] is True
    assert report['plan']['version'] == VERSION
    assert report['physical_tables'][0]['rows'] == 3
    assert 'First' not in json.dumps(report)  # Receipts are aggregate metadata.


def test_full_parent_index_rejects_unused_duplicate_after_sample_boundary(tmp_path):
    text = 'Code,Label,Region\n' + ''.join(f'{i},label,N\n' for i in range(1005)) + '1004,duplicate,S\n'
    resource, files, join = fixture(tmp_path, text)
    with pytest.raises(ValidationFailure) as exc:
        LookupIndex(resource, files, join, tmp_path / 'work')
    assert code(exc) == 'LOOKUP_PARENT_NOT_UNIQUE'
    assert exc.value.qa[0]['metrics']['row_locator'] == 'csv:1006'
    # No leaked connection after constructor failure.
    path = next((tmp_path / 'work').glob('*.sqlite'))
    with sqlite3.connect(path, timeout=0) as db:
        db.execute('BEGIN EXCLUSIVE')


def test_sample_child_can_resolve_parent_beyond_1000_rows(tmp_path):
    resource, files, join = fixture(tmp_path, 'Code,Label,Region\n' + ''.join(f'{i},label{i},N\n' for i in range(1005)))
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        assert index.resolve({'Type': '1004'})['values']['Label'] == 'label1004'
        assert index.receipt()['metrics']['unused_parent_keys'] == 1004


def test_composite_key_order_and_optional_association(tmp_path):
    resource, files, join = fixture(tmp_path, 'Code,Part,Label,Region\nA,01,First,N\n01,A,Second,S\n')
    resource['key'] = ['Code', 'Part']
    join.update(fields=['C', 'P'], allow_blank=True)
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        assert index.resolve({'C': 'A', 'P': '01'})['values']['Label'] == 'First'
        assert index.resolve({'C': '01', 'P': 'A'})['values']['Label'] == 'Second'
        blank = index.resolve({'C': None, 'P': ''})
        assert blank == {'status': 'not_associated', 'values': {'Label': None, 'Region': None}, 'lineage': None}
        assert index.receipt()['metrics']['all_blank'] == 1
        with pytest.raises(ValidationFailure) as exc:
            index.resolve({'C': 'A', 'P': None})
        assert code(exc) == 'LOOKUP_KEY_INCOMPLETE'
        with pytest.raises(ValidationFailure):
            index.receipt()  # Cannot catch and discard a rejected source row.


def test_unmatched_unknown_is_distinct_from_matched_null_and_no_association(tmp_path):
    file = admitted(tmp_path, 'parent.json', '[{"Code":"A","Label":null,"Region":"N"}]')
    resource, _, join = fixture(tmp_path)
    resource['file_id'] = file['id']
    join.update(allow_blank=True, on_missing='preserve_unknown')
    with LookupIndex(resource, [file], join, tmp_path / 'work') as index:
        matched = index.resolve({'Type': 'A'})
        unmatched = index.resolve({'Type': 'B'})
        blank = index.resolve({'Type': None})
        assert [row['status'] for row in [matched, unmatched, blank]] == ['matched', 'unmatched', 'not_associated']
        assert matched['lineage'] and unmatched['lineage'] is None
        assert matched['values']['Label'] is None
        assert index.receipt()['metrics']['unmatched'] == 1


@pytest.mark.parametrize('value,expected', [(None, 'LOOKUP_KEY_INCOMPLETE'), ('', 'LOOKUP_KEY_INCOMPLETE'),
                                           ('   ', 'LOOKUP_KEY_INCOMPLETE'), (True, 'LOOKUP_KEY_INVALID'),
                                           (['001'], 'LOOKUP_KEY_INVALID'), ({'x': 1}, 'LOOKUP_KEY_INVALID'),
                                           (float('nan'), 'LOOKUP_KEY_INVALID'), ('missing', 'LOOKUP_UNMATCHED')])
def test_invalid_child_keys_invalidate_final_receipt(tmp_path, value, expected):
    resource, files, join = fixture(tmp_path)
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        with pytest.raises(ValidationFailure) as exc:
            index.resolve({'Type': value})
        assert code(exc) == expected
        with pytest.raises(ValidationFailure):
            index.resolve({'Type': '001'})
        with pytest.raises(ValidationFailure):
            index.receipt()


def test_union_parents_have_exact_member_lineage_and_global_uniqueness(tmp_path):
    resource, files, join = fixture(tmp_path, 'Code,Label,Region\n001,First,N\n')
    second = admitted(tmp_path, 'second.csv', 'Region,Label,Code\nS,Second,1\n')
    files.append(second)
    resource['partitions'] = [{'file_id': file['id'], 'table': {}} for file in files]
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        assert index.resolve({'Type': '1'})['lineage']['file_sha256'] == second['sha256']
        receipt = index.receipt()
        assert [part['rows'] for part in receipt['physical_tables']] == [1, 1]
    second = admitted(tmp_path, 'second.csv', 'Region,Label,Code\nS,Conflicting,001\n')
    with pytest.raises(ValidationFailure) as exc:
        LookupIndex(resource, [files[0], second], join, tmp_path / 'other')
    assert code(exc) == 'LOOKUP_PARENT_NOT_UNIQUE'


def test_rename_does_not_change_plan_or_resolved_lineage(tmp_path):
    resource, files, join = fixture(tmp_path)
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        plan, row = index.plan, index.resolve({'Type': '001'})
    renamed = copy.deepcopy(resource)
    renamed['file_id'] = 'new-id'
    with LookupIndex(renamed, [{**files[0], 'id': 'new-id', 'name': 'renamed.csv'}], join, tmp_path / 'other') as index:
        assert index.plan == plan
        assert index.resolve({'Type': '001'}) == row


def test_input_tampering_before_parse_and_after_index_is_detected(tmp_path):
    resource, files, join = fixture(tmp_path)
    stale = [{**files[0], 'sha256': '0' * 64}]
    with patch('arsia_pipeline.lookup_plan.detect_tables', side_effect=AssertionError('must check bytes before parsing')):
        with pytest.raises(ValidationFailure) as exc:
            prepare_lookup(resource, stale, join)
        assert code(exc) == 'LOOKUP_INPUT_CHANGED'
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        # Mutation of caller descriptors cannot re-pin the internal snapshot.
        Path(files[0]['path']).write_text('Code,Label,Region\n001,Changed,N\n')
        files[0]['sha256'] = hashlib.sha256(Path(files[0]['path']).read_bytes()).hexdigest()
        with pytest.raises(ValidationFailure) as exc:
            index.receipt()
        assert code(exc) == 'LOOKUP_INPUT_CHANGED'


@pytest.mark.parametrize('fault', ['wrong_purpose', 'expression', 'filter', 'default', 'missing_field', 'missing_child_field',
                                 'missing_parent_key', 'key_arity', 'duplicate_key_field', 'unadmitted', 'nonboolean'])
def test_plan_does_not_accept_hidden_filters_defaults_or_undefined_fields(tmp_path, fault):
    resource, files, join = fixture(tmp_path)
    if fault == 'wrong_purpose': resource['purpose'] = 'fact'
    if fault == 'expression': join['expression'] = 'lambda row: row[0]'
    if fault == 'filter': resource['table']['skip_rows'] = 1
    if fault == 'default': join['on_missing'] = 'zero'
    if fault == 'missing_field': join['select'] = ['Invented']
    if fault == 'missing_parent_key': resource['key'] = ['Invented']
    if fault == 'key_arity': join['fields'] = ['Type', 'Year']
    if fault == 'duplicate_key_field': resource['key'] = ['Code', 'Code']
    if fault == 'unadmitted': resource['file_id'] = 'missing'
    if fault == 'nonboolean': join['allow_blank'] = 'true'
    with pytest.raises((UnsupportedCapability, ValidationFailure)):
        with LookupIndex(resource, files, join, tmp_path / 'work') as index:
            index.resolve({} if fault == 'missing_child_field' else {'Type': '001'})


def test_plan_and_receipt_copies_cannot_change_execution(tmp_path):
    resource, files, join = fixture(tmp_path)
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        plan = index.plan
        plan['select'] = ['malicious']
        receipt = index.receipt()
        receipt['physical_tables'].clear()
        join['select'].append('malicious')
        assert index.resolve({'Type': '001'})['values'] == {'Label': 'First', 'Region': 'N'}
        assert len(index.receipt()['physical_tables']) == 1


def test_cancellation_and_closed_index_cannot_be_reused(tmp_path):
    resource, files, join = fixture(tmp_path)
    def cancelled(): raise ImportCancelled()
    with pytest.raises(ImportCancelled):
        LookupIndex(resource, files, join, tmp_path / 'work', cancelled)
    index = LookupIndex(resource, files, join, tmp_path / 'work')
    index.cancelled = cancelled
    with pytest.raises(ImportCancelled): index.resolve({'Type': '001'})
    with pytest.raises(ValidationFailure): index.receipt()
    index.close()
    with pytest.raises(ValidationFailure): index.resolve({'Type': '001'})


def test_literal_sql_like_identifiers_and_whitespace_are_not_rewritten(tmp_path):
    resource, files, join = fixture(tmp_path, "Code,Label,Region\n' OR 1=1 --,Literal,N\n 001 ,Spaced,S\n")
    with LookupIndex(resource, files, join, tmp_path / 'work') as index:
        assert index.resolve({'Type': "' OR 1=1 --"})['values']['Label'] == 'Literal'
        assert index.resolve({'Type': ' 001 '})['values']['Label'] == 'Spaced'
        with pytest.raises(ValidationFailure) as exc: index.resolve({'Type': '001'})
        assert code(exc) == 'LOOKUP_UNMATCHED'
