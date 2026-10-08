"""Development-only test source. Not executed in the 2026-10-02 handoff.

These unit cases do not replace the user-supplied dataset acceptance checklist.
"""
import copy
import hashlib

import pytest

from arsia_pipeline.adapter_reuse import csv_shape, measured_coverage, VersionCandidateDeclined
from arsia_pipeline.capability_preflight import (
    adaptation_enabled, classified_blockers, operation_support, require_supported_operations,
    requires_system_change,
)
from arsia_pipeline.errors import NeedsInput, ModelUnavailable, UnsupportedCapability, ValidationFailure
from arsia_pipeline.issue_progress import host_scope, issue_identity


@pytest.mark.parametrize('value', [None, False, 1, 'true', {}, []])
def test_only_explicit_trusted_boolean_enables_adaptation(value):
    assert adaptation_enabled({'autonomous_adaptation_v1': value}) is False
    assert adaptation_enabled({'autonomous_adaptation_v1': True}) is True
    assert adaptation_enabled({'options': {'autonomous_adaptation_v1': True}}) is False


def test_system_block_keeps_action_owner_and_original_subject():
    exc = UnsupportedCapability('LOOKUP_DATE_SEMANTICS_UNSUPPORTED', 'No reviewed date semantics')
    exc.details['blockers'][0]['details'] = {'role': 'crash', 'field': 'DATE'}
    rows = classified_blockers(exc, operation='preflight_contract')
    assert requires_system_change({'blockers': rows})
    assert rows[0]['subject'] == {'role': 'crash', 'field': 'DATE'}
    assert rows[0]['responsible_party'] == 'system'
    assert rows[0]['next_action'] and rows[0]['resumable_when']


def test_missing_crs_and_transport_are_not_adapter_errors():
    missing = NeedsInput('Unknown coordinate reference', details={
        'grounding': {'issues': [{'code': 'CRS_UNGROUNDED', 'role': 'crash'}]}})
    assert classified_blockers(missing)[0]['kind'] == 'evidence_missing'
    assert classified_blockers(ModelUnavailable('Transport refused'))[0]['kind'] == 'model_transport'


def test_duplicate_parent_and_projection_mismatch_have_different_owners():
    raw = ValidationFailure('Duplicate parent', [{'code': 'LOOKUP_PARENT_NOT_UNIQUE', 'metrics': {'row_locator': 'csv:9'}}])
    adapter = ValidationFailure('Projection differs', [{'code': 'QA06_RECONCILIATION', 'metrics': {'row_locator': 'csv:9'}}])
    assert classified_blockers(raw)[0]['responsible_party'] == 'source_owner'
    assert classified_blockers(adapter)[0]['kind'] == 'adapter_revision'


def test_operation_inventory_has_real_verifiers_and_rejects_aggregate():
    c = {'resources': [{'role': 'crash', 'grain': 'crash', 'partitions': [{}, {}],
                        'lookups': [{'name': 'code'}]}]}
    result = operation_support(c)
    assert {r['operation'] for r in result['operations']} == {'row_projection', 'homogeneous_union', 'unique_lookup'}
    assert all(r['verifier'] for r in result['operations'])
    assert result['admission'] is False
    with pytest.raises(NeedsInput) as error:
        require_supported_operations({'resources': [{'role': 'totals', 'grain': 'observation'}]})
    assert requires_system_change(error.value.details)


def test_new_url_source_hint_and_key_edit_do_not_renew_same_problem():
    first = {'source': {'source_id': 'one', 'dataset_url': 'https://one.gov.au/dataset'},
             'resources': [{'role': 'crash', 'grain': 'crash', 'key': ['ID']}]}
    second = copy.deepcopy(first)
    second['source'] = {'source_id': 'two', 'dataset_url': 'https://two.gov.au/new'}
    second['resources'][0]['key'] = ['ChangedProposal']
    files = [{'id': 'upload', 'sha256': 'a'*64}]
    refreshed = files + [{'id': 'doc', 'sha256': 'b'*64, 'role': 'public_evidence'}]
    issue = {'code': 'CRS_UNGROUNDED', 'role': 'crash', 'field': 'X'}
    a = issue_identity(issue, host_scope(first, files, 'policy', stable_subjects=True), 'preflight')
    b = issue_identity(issue, host_scope(second, refreshed, 'policy', stable_subjects=True), 'preflight')
    assert a == b
    # Existing checkpoint scope keeps its old representation unless opted in.
    assert host_scope(first, files, 'policy')['dataset_url'] == first['source']['dataset_url']


def admitted(path, data):
    path.write_bytes(data)
    return {'id': 'file', 'path': str(path), 'name': path.name,
            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def test_csv_shape_uses_name_mapping_but_rejects_schema_drift(tmp_path):
    a = admitted(tmp_path/'a.csv', b'ID,DATE\n001,2024-01-01\n')
    b = admitted(tmp_path/'b.csv', b'DATE,ID\n2025-02-01,002\n')
    c = admitted(tmp_path/'c.csv', b'ID,DATE,EXTRA\n001,2024-01-01,x\n')
    assert csv_shape(a, {})[0] == csv_shape(b, {})[0]
    assert csv_shape(a, {})[0] != csv_shape(c, {})[0]
    with pytest.raises(VersionCandidateDeclined, match='PARSER_PLAN'):
        csv_shape(a, {'skip_rows': 1})


def test_new_coverage_scans_all_input_dates_without_old_coverage_filter(tmp_path):
    file = admitted(tmp_path/'a.csv', b'ID,DATE\n001,2024-01-01\n002,2025-02-03\n')
    contract = {'source': {'coverage': {'from': '2024-01-01', 'to': '2024-12-31'}},
                'resources': [{'role': 'crash', 'grain': 'crash', 'file_id': 'file',
                               'mapping': {'date': {'field': 'DATE', 'formats': ['%Y-%m-%d']}}}]}
    coverage, count = measured_coverage(contract, [file], lambda: None)
    assert coverage == {'from': '2024-01-01', 'to': '2025-02-03'}
    assert count == 2
    assert contract['source']['coverage']['to'] == '2024-12-31'


def test_equivalent_version_recipes_ignore_old_coverage_not_mapping():
    from arsia_pipeline.adapter_reuse import version_signature
    record = {'contract': {'source': {'coverage': {'from': '2024-01-01', 'to': '2024-12-31'}},
                           'resources': [{'role': 'crash', 'file_id': 'old', 'key': ['ID'], 'table': {}}]},
              'version_candidate': {'resources': [{'role': 'crash', 'shape': {'fields': ['DATE','ID'], 'encoding': 'utf-8'}}]},
              'documents': [], 'dependencies': {}, 'image': 'sha256:fixture'}
    changed = copy.deepcopy(record)
    changed['contract']['source']['coverage'] = {'from': '2025-01-01', 'to': '2025-12-31'}
    changed['contract']['resources'][0].update(file_id='new', table={'header': ['DATE', 'ID']})
    assert version_signature(record) == version_signature(changed)
    changed['contract']['resources'][0]['key'] = ['DATE']
    assert version_signature(record) != version_signature(changed)
