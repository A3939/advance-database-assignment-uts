import copy
import json

import pytest

from arsia_pipeline.adapter_sdk import AdapterContext
from arsia_pipeline.canonical import ContractError
from arsia_pipeline.errors import UnsupportedCapability, ValidationFailure
from arsia_pipeline.lookup_projection import LookupProjection
from arsia_pipeline.trusted_qa import validate_contract
from test_canonical_v2 import contract
from test_lookup_plan import admitted


def bundle(tmp_path):
    c = contract()
    child = admitted(tmp_path, 'child.csv', 'ID,DATE,Type,INJURED\n001,30/04/2024 13:20,A,3\n002,01/05/2024 13:20,B,1\n')
    parent = admitted(tmp_path, 'codes.csv', 'Code,Class,Deaths,X,Y\nA,F,2,149.1,-35.2\nB,U,0,149.2,-35.3\n')
    r = c['resources'][0]
    r['file_id'] = child['id']
    r['lookups'] = [{'name': 'code', 'parent': 'codes', 'fields': ['Type'],
                     'select': ['Class', 'Deaths', 'X', 'Y'], 'allow_blank': False, 'on_missing': 'error'}]
    r['mapping']['severity']['field'] = {'lookup': 'code', 'field': 'Class'}
    r['mapping']['fatalities'] = {'field': {'lookup': 'code', 'field': 'Deaths'}}
    r['mapping']['casualties'] = {'sum_fields': ['INJURED', {'lookup': 'code', 'field': 'Deaths'}]}
    r['mapping']['geography'] = {'crs': 'EPSG:4326', 'x_field': {'lookup': 'code', 'field': 'X'},
                               'y_field': {'lookup': 'code', 'field': 'Y'}}
    c['evidence']['geography'] = [{'document_id': 'synthetic', 'quote': 'Test fixture only; not authoritative CRS evidence.'}]
    c['lookup_tables'] = [{'role': 'codes', 'purpose': 'lookup', 'file_id': parent['id'], 'table': {}, 'key': ['Code']}]
    return c, [child, parent]


def test_sdk_projects_typed_fields_without_changing_keys_or_raw_rows(tmp_path):
    c, files = bundle(tmp_path)
    original = copy.deepcopy(c)
    output = tmp_path / 'output'
    output.mkdir()
    ctx = AdapterContext(c, files, output, 'sample')
    try:
        raw_rows = []
        for locator, raw in ctx.iter_rows('crash'):
            raw_rows.append(copy.deepcopy(raw))
            projected = ctx.project('crash', locator, raw)
            assert raw == raw_rows[-1]
            ctx.emit('crash', projected)
        receipts = ctx.lookup_projection.receipts()
    finally:
        ctx.close()
    rows = [json.loads(line) for line in (output / 'crashes.jsonl').read_text().splitlines()]
    assert c == original
    assert [row['raw_key'] for row in rows] == [['001'], ['002']]
    assert [row['extensions'] for row in rows] == raw_rows
    assert [row['fatalities'] for row in rows] == [2, 0]
    assert [row['casualties'] for row in rows] == [5, 1]
    assert [row['raw_severity'] for row in rows] == ['F', 'U']
    assert [row['coordinates'] for row in rows] == [[149.1, -35.2], [149.2, -35.3]]
    assert [row['lookup_lineage']['code']['parent']['row_locator'] for row in rows] == ['csv:1', 'csv:2']
    assert all(row['lookup_lineage']['code']['parent']['file_sha256'] == files[1]['sha256'] for row in rows)
    assert '\\u0000lookup' not in json.dumps(rows)
    assert receipts[0]['metrics']['parent_rows'] == 2 and receipts[0]['metrics']['requests'] == 2
    assert receipts[0]['admission'] is False


@pytest.mark.parametrize('fault', ['unknown_lookup', 'unknown_selected_field', 'unused_lookup', 'unused_table',
                                  'duplicate_role', 'duplicate_name', 'chained_key', 'free_expression'])
def test_projection_requires_explicit_closed_typed_bindings(tmp_path, fault):
    c, files = bundle(tmp_path)
    r = c['resources'][0]
    if fault == 'unknown_lookup': r['mapping']['severity']['field']['lookup'] = 'unknown'
    if fault == 'unknown_selected_field': r['mapping']['severity']['field']['field'] = 'Label'
    if fault == 'unused_lookup': r['lookups'].append({**r['lookups'][0], 'name': 'unused'})
    if fault == 'unused_table': c['lookup_tables'].append({**c['lookup_tables'][0], 'role': 'unused'})
    if fault == 'duplicate_role': c['lookup_tables'][0]['role'] = 'crash'
    if fault == 'duplicate_name': r['lookups'].append(copy.deepcopy(r['lookups'][0]))
    if fault == 'chained_key': r['lookups'][0]['fields'] = [{'lookup': 'code', 'field': 'Class'}]
    if fault == 'free_expression': r['mapping']['fatalities']['field'] = {'expression': '2'}
    with pytest.raises(ValidationFailure):
        LookupProjection(c, files, tmp_path / 'work')


def test_projection_failure_cannot_be_caught_to_claim_successful_receipts(tmp_path):
    c, files = bundle(tmp_path)
    projection = LookupProjection(c, files, tmp_path / 'work')
    try:
        with pytest.raises(ContractError):
            projection.project('crash', 'csv:1', {'ID': '001', 'DATE': 'invalid', 'Type': 'A', 'INJURED': '3'})
        with pytest.raises(ValidationFailure): projection.receipts()
    finally:
        projection.close()


@pytest.mark.parametrize('declaration', ['both', 'tables_only', 'bindings_only'])
def test_provisional_execution_does_not_bypass_missing_admission_integration(tmp_path, declaration):
    c, files = bundle(tmp_path)
    if declaration == 'tables_only': c['resources'][0].pop('lookups')
    if declaration == 'bindings_only': c.pop('lookup_tables')
    if declaration != 'both':
        with pytest.raises(ValidationFailure): validate_contract(c, files)
    else:
        from arsia_pipeline.capability_preflight import preflight_contract
        assert set(validate_contract(c, files)) == {'crash'}
        preflight = preflight_contract(c, files, tmp_path)
        assert preflight['ok'] is False and preflight['admission'] is False
        assert preflight['blockers'][0]['code'] == 'evidence_needed'


def test_lookup_absent_field_is_not_confused_with_explicit_null(tmp_path):
    from arsia_pipeline.lookup_plan import LookupIndex
    resource = {'role': 'codes', 'purpose': 'lookup', 'file_id': 'parent.json', 'table': {}, 'key': ['Code']}
    file = admitted(tmp_path, 'parent.json', '[{"Code":"A"},{"Code":"B","Label":null}]')
    join = {'child_role': 'crash', 'fields': ['Code'], 'select': ['Label'], 'allow_blank': False, 'on_missing': 'error'}
    with pytest.raises(ValidationFailure) as exc:
        LookupIndex(resource, [file], join, tmp_path / 'work')
    assert exc.value.qa[0]['code'] == 'LOOKUP_VALUE_FIELD_ABSENT'
