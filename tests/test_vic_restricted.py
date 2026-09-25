"""Restricted manifest transport and QA guards; native/SQL replies are labelled mocks."""
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import shutil
from uuid import UUID

import pytest

from arsia_ingest import qa_input
from arsia_ingest.fingerprint import FP1Operation, fingerprint
from arsia_ingest.manifest import REQUIRED_CHECKS, FrozenManifest, digest_inventory, freeze_manifest
from arsia_ingest.models import IntakeError, NativeRow
from arsia_ingest.vic_restricted import (
    PINS, PROTOCOL, check_profile_evidence, input_expectations, vic_restricted_definitions,
)
from test_fingerprint import DIGEST, ENVIRONMENT, ScriptedConnection
from test_manifest import build
from test_qa_input import RawConnection


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_policy_copies_match_pins_outside_the_checkout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for path, expected in PINS.items():
        data = files("arsia_ingest").joinpath("policies", Path(path).name).read_bytes()
        assert data == (ROOT / path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == expected
    definitions = vic_restricted_definitions()
    assert definitions["qa_contract"]["version"] == PROTOCOL
    definitions["contracts"].clear()
    assert len(vic_restricted_definitions()["contracts"]) == 4


@pytest.mark.parametrize("change", ["missing", "changed", "symlink"])
def test_packaged_policies_keep_integrity_checks(tmp_path, monkeypatch, change):
    from arsia_ingest import vic_restricted

    policies = tmp_path / "policies"
    policies.mkdir()
    for path in PINS:
        shutil.copyfile(ROOT / path, policies / Path(path).name)
    original = next(iter(PINS))
    target = policies / Path(original).name
    target.unlink()
    if change == "changed":
        target.write_text("{}", encoding="utf-8")
    elif change == "symlink":
        target.symlink_to(ROOT / original)
    monkeypatch.setattr(vic_restricted, "files", lambda package: tmp_path)
    with pytest.raises(IntakeError):
        vic_restricted_definitions()


@pytest.fixture
def vic_build(build):
    definitions = vic_restricted_definitions()
    project, inventory = build[1]['project_root'], deepcopy(build[1]['inventory'])
    for path in PINS:
        target = project / path
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    inventory['components']['intake'].extend(PINS)
    files = [c['content']['input'] for c in definitions['contracts']]
    value = {
        'contract_version': 'team-v1.1', 'dataset_kind': 'official',
        'analysis': definitions['analysis'], 'sources': definitions['sources'], 'files': files,
        'rules': {key: definitions[key] for key in ('contracts', 'mappings', 'severity', 'qa_contract')},
        'required_checks': list(REQUIRED_CHECKS),
        'provenance': {'prepared_at': '2026-09-23T00:00:00Z', 'prepared_by': 'transport-test-only',
                       'files': [{'resource_id': f['resource_id'], 'file_sha256': f['file_sha256'],
                                  'archive_relpath': f"official/archive/sha256/{f['file_sha256'][:2]}/{f['file_sha256']}",
                                  'original_filename': f['resource_role'] + '.csv',
                                  'download_url': 'https://opendata.transport.vic.gov.au/',
                                  'evidence_ref': 'Transport test metadata, not a prepared run.'} for f in files]},
    }
    value['rules'].update(digest_inventory(project, inventory))
    return freeze_manifest(value, project_root=project, inventory=inventory), project, inventory


def test_freezes_exact_policy_cases_dispositions_and_all_seven_checks(vic_build):
    frozen, _, _ = vic_build
    value = frozen.as_dict()
    assert isinstance(frozen, FrozenManifest)
    assert len(value['files']) == 4
    assert sum(f['raw_count'] for f in value['files']) == 1439470
    assert value['required_checks'] == list(REQUIRED_CHECKS)
    policy = value['rules']['mappings'][0]['content']
    assert len(policy['unresolved_definitions']) == 10
    assert policy['runtime_integrated'] is False
    assert not policy['full_source_contract_confirmed']
    assert not policy['publisher_bundle_confirmed']
    assert all(c['status'] == 'restricted' for c in value['rules']['contracts'])
    assert 'provenance' not in frozen.fingerprint_input()
    value['rules']['mappings'][0]['content']['cases'].clear()
    assert frozen.as_dict()['rules']['mappings'][0]['content']['cases']


@pytest.mark.parametrize('change', [
    'hash', 'count', 'parser', 'header', 'missing_file', 'scope', 'source', 'kind',
    'policy_case', 'policy_disposition', 'policy_output', 'severity', 'confirmed',
    'draft', 'clear_unresolved', 'mapping_version', 'legacy', 'qa_text', 'inventory',
])
def test_rejects_changes_even_when_versions_and_counts_are_reused(vic_build, change):
    value = vic_build[0].as_dict()
    file = value['files'][0]
    contract = next(c for c in value['rules']['contracts'] if c['id'] == file['resource_id'])
    policy = value['rules']['mappings'][0]['content']
    if change in ('hash', 'count', 'parser', 'header'):
        key, replacement = {'hash': ('file_sha256', 'a' * 64), 'count': ('raw_count', 1),
                            'parser': ('parser_version', 'csv-native-v2'), 'header': ('header', ['ACCIDENT_NO'])}[change]
        file[key] = replacement
        contract['content']['input'][key] = replacement
    elif change == 'missing_file': value['files'].pop()
    elif change == 'scope': value['analysis']['year_to'] = 2023
    elif change == 'source': value['sources'][0]['release_label'] = 'Publisher approved'
    elif change == 'kind': value['dataset_kind'] = 'synthetic'
    elif change == 'policy_case': policy['cases']['unmatched_person_vehicle'][0]['person_id'] = 'invented'
    elif change == 'policy_disposition': policy['unresolved_definitions'].pop()
    elif change == 'policy_output': policy['retention']['vic_map_eligible'] = True
    elif change == 'severity': value['rules']['severity'][0]['is_fatal_crash'] = False
    elif change in ('confirmed', 'draft'):
        contract['status'] = contract['content']['confirmation']['status'] = change
    elif change == 'clear_unresolved': contract['content']['confirmation']['unresolved'] = []
    elif change == 'mapping_version': value['rules']['mappings'][0]['version'] = 'other-v1'
    elif change == 'legacy': value['rules']['qa_contract'] = json.loads((ROOT / 'config/qa-team-v1.1.json').read_text())
    elif change == 'qa_text': value['rules']['qa_contract']['content']['text'] += '\nApproved by nobody.'
    elif change == 'inventory': value['rules']['code_files'] = [x for x in value['rules']['code_files'] if x['path'] not in PINS]
    with pytest.raises(IntakeError):
        FrozenManifest(json.dumps(value))


def test_missing_real_component_inventory_still_blocks(vic_build):
    frozen, project, inventory = vic_build
    del inventory['components']['publish']
    with pytest.raises(IntakeError, match='every build component'):
        freeze_manifest(frozen.as_dict(), project_root=project, inventory=inventory)


def test_new_protocol_cannot_be_selected_by_version_label_alone(vic_build):
    value = vic_build[0].as_dict()
    value['rules']['qa_contract']['content'] = json.loads((ROOT / 'config/qa-team-v1.1.json').read_text())['content']
    with pytest.raises(IntakeError, match='protocol changes need a reviewed version'):
        FrozenManifest(json.dumps(value))


def test_real_frozen_manifest_reaches_fp1_with_no_provenance(vic_build):
    frozen, project, _ = vic_build
    connection = ScriptedConnection([ENVIRONMENT, [(True,)], [(DIGEST,)]])
    operation = FP1Operation('review_test', 'fp1', 'test-v1', 160004, 'sql/fp1.sql')
    assert fingerprint(connection, frozen, operation, project_root=project) == DIGEST
    sent = json.loads(connection.calls[-1][1][0])
    assert sent == frozen.fingerprint_input()
    assert sent['rules']['qa_contract']['version'] == PROTOCOL
    assert sent['rules']['mappings'][0]['content']['cases']
    assert 'provenance' not in sent
    with pytest.raises(IntakeError) as error:
        fingerprint(connection, frozen, project_root=project)
    assert error.value.code == 'FP1_UNAVAILABLE'


def test_all_portable_evidence_bytes_match_the_frozen_register():
    binding = check_profile_evidence(ROOT)
    assert len(binding['files']) == 15
    assert binding['semantic_checks_executed'] is False


@pytest.fixture
def mocked_native(vic_build, monkeypatch):
    value = vic_build[0].as_dict()
    files = {f['resource_id']: f for f in value['files']}
    monkeypatch.setattr(qa_input, '_hash', lambda path: path.name)
    def rows(path, spec, stats):
        stats.header = list(spec.header)
        stats.raw_count = files[spec.resource_id]['raw_count']
        yield NativeRow('csv:2', {key: '' for key in spec.header})
    monkeypatch.setattr(qa_input, 'iter_native_rows', rows)
    return value


def qa(value, tmp_path, **kwargs):
    kwargs.setdefault('policy_evidence_root', ROOT)
    return qa_input.check_inputs(value, tmp_path / 'mock-archive', evidence_dir=tmp_path / 'qa',
                                producer_version='mock-native-vic-test-v1',
                                supported_mappings=value['rules']['mappings'], **kwargs)


def test_qa01_new_expectations_preserve_false_full_source_flags(mocked_native, tmp_path):
    report = qa(mocked_native, tmp_path)
    assert not report.blocked
    assert len(report.rows) == 5
    for row in report.rows[:-1]:
        assert row['actual'] == row['expected']
        assert row['actual']['metrics'] == input_expectations()
        detail = row['evidence']['references'][0]['detail']
        data = Path(detail['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == detail['sha256']
        assert b'"semantic_checks_executed": false' in data


@pytest.mark.parametrize('change', ['missing', 'changed', 'symlink'])
def test_missing_or_changed_case_evidence_blocks_not_pass(mocked_native, tmp_path, change):
    root = tmp_path / 'evidence-root'
    for relative in PINS:
        dest = root / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, dest)
    target = root / 'docs/sources/evidence/vic/followup-2026-09-23/evidence/local-review.json'
    target.parent.mkdir(parents=True)
    if change == 'changed': target.write_text('{}')
    elif change == 'symlink': target.symlink_to(ROOT / target.relative_to(root))
    report = qa(mocked_native, tmp_path, policy_evidence_root=root)
    assert report.blocked
    for row in report.rows[:-1]:
        assert row['actual']['metrics']['case_register_match'] is False
        assert row['actual']['metrics']['hash_match'] is None
        assert row['actual']['evaluated_count'] == 0


def test_profile_does_not_accept_unrestricted_review_override(mocked_native, tmp_path):
    report = qa(mocked_native, tmp_path, official_reviews=[{'resource_id': 'official_vic_person', 'bundle_confirmed': True}])
    assert report.blocked
    assert any('RESTRICTED_REVIEW_CONFLICT' in r['evidence']['reason_codes'] for r in report.rows)


def test_qa02_still_checks_raw_values_under_new_protocol(mocked_native, tmp_path):
    records = [[str(UUID(int=i + 1)), f['source_id'], f['resource_id'], f['file_sha256'],
                f['parser_version'], 'csv:2', {key: '' for key in f['header']}]
               for i, f in enumerate(mocked_native['files'])]
    records[0][-1]['ACCIDENT_NO'] = 'invented'
    connection = RawConnection(records)
    report = qa_input.check_raw(connection, mocked_native, tmp_path / 'mock-archive',
                               evidence_dir=tmp_path / 'raw', producer_version='mock-native-vic-test-v1')
    assert report.blocked
    assert report.rows[0]['actual']['metrics']['payload_mismatch_count'] == 1
    assert len(connection.calls) == 4
    assert all('raw.record' in statement for statement, _ in connection.calls)


@pytest.mark.parametrize('change', ['hash', 'header', 'count', 'unavailable'])
def test_native_failures_still_block_restricted_qa01(mocked_native, tmp_path, monkeypatch, change):
    if change == 'hash':
        monkeypatch.setattr(qa_input, '_hash', lambda path: '0' * 64)
    elif change == 'unavailable':
        def unavailable(path):
            raise FileNotFoundError('Missing test archive')
        monkeypatch.setattr(qa_input, '_hash', unavailable)
    else:
        original = qa_input.iter_native_rows
        def rows(path, spec, stats):
            yield from original(path, spec, stats)
            if change == 'header': stats.header = ['WRONG_HEADER']
            else: stats.raw_count -= 1
        monkeypatch.setattr(qa_input, 'iter_native_rows', rows)
    report = qa(mocked_native, tmp_path)
    assert report.blocked
    assert all(r['result'] == 'block' for r in report.rows)
    expected = {'hash': 'QA_HASH', 'header': 'HEADER_MISMATCH', 'count': 'NATIVE_COUNT_MISMATCH',
                'unavailable': 'INPUT_CHECK_UNAVAILABLE'}[change]
    assert all(expected in r['evidence']['reason_codes'] for r in report.rows[:-1])


def test_other_source_still_requires_its_own_confirmed_review(mocked_native, tmp_path, monkeypatch):
    value = deepcopy(mocked_native)
    file = deepcopy(value['files'][0])
    file.update(source_id='official_other', resource_id='official_other_crash')
    source = deepcopy(value['sources'][0])
    source.update(source_id='official_other', jurisdiction_code='OTHER', resource_ids=[file['resource_id']])
    contract = deepcopy(value['rules']['contracts'][0])
    contract.update(id=file['resource_id'], status='confirmed', mapping_ids=['other_mapping'])
    contract['content']['input'] = file
    contract['content']['identity']['resource_ids'] = source['resource_ids']
    contract['content']['confirmation'].update(status='confirmed', unresolved=[])
    value['files'].append(file)
    value['sources'].append(source)
    value['rules']['contracts'].append(contract)
    value['rules']['mappings'].append({'id': 'other_mapping', 'version': 'test-v1', 'content': {'basis': 'Test transport only'}})
    value['rules']['severity'].extend([{**s, 'source_id': 'official_other'} for s in list(value['rules']['severity'])])
    value['provenance']['files'].append({**value['provenance']['files'][0], 'resource_id': file['resource_id']})
    value = FrozenManifest(json.dumps(value)).as_dict()
    def rows(path, spec, stats):
        stats.header = list(spec.header)
        stats.raw_count = next(f['raw_count'] for f in value['files'] if f['resource_id'] == spec.resource_id)
        yield NativeRow('csv:2', {key: '' for key in spec.header})
    monkeypatch.setattr(qa_input, 'iter_native_rows', rows)
    report = qa(value, tmp_path)
    other = next(r for r in report.rows if 'official_other_crash' in r['object_key'])
    assert other['result'] == 'block'
    assert other['actual']['metrics'] == {'hash_match': True, 'header_match': True,
                                           'bundle_confirmed': False, 'contract_confirmed': False}
    assert other['evidence']['reason_codes'] == ['BUNDLE_UNCONFIRMED', 'CONTRACT_UNCONFIRMED']
    assert sum(r['result'] == 'pass' for r in report.rows) == 4


def test_identity_set_order_is_normalized_but_case_order_is_preserved(vic_build):
    original = vic_build[0]
    value = original.as_dict()
    value['files'].reverse()
    value['sources'][0]['resource_ids'].reverse()
    value['rules']['contracts'].reverse()
    value['rules']['severity'].reverse()
    value['rules']['code_files'].reverse()
    for contract in value['rules']['contracts']:
        contract['content']['identity']['resource_ids'].reverse()
        contract['content']['semantics']['severity_codes'].reverse()
    assert FrozenManifest(json.dumps(value))._json == original._json
    value['rules']['mappings'][0]['content']['cases']['unmatched_person_vehicle'].reverse()
    with pytest.raises(IntakeError, match='complete adopted VIC policy'):
        FrozenManifest(json.dumps(value))
