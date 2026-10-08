import copy
import json
from pathlib import Path

import pytest

from arsia_pipeline.errors import NeedsInput, ValidationFailure
from arsia_pipeline.source_completeness import VERSION, verify_arcgis_export, review_completeness, require_removal_authority
import test_public_sources as public_fixtures

URL = 'https://source.gov.au/FeatureServer/0'


def export(tmp_path, for_admission=False):
    test = public_fixtures.PublicTests(); test.root = tmp_path
    result = test.arcgis_tool(page_reference={'wkid': 4326 if for_admission else 3857}, for_admission=for_admission).fetch_arcgis_layer(URL)
    return result, result['__files'][0]


def verify(result, file, root):
    return verify_arcgis_export(file, root=root, source_url=URL, metadata_sha256=result['metadata_sha256'])


def test_exact_export_reconstructs_all_pages_and_membership(tmp_path):
    result, file = export(tmp_path)
    proof = verify(result, file, tmp_path)
    assert proof['status'] == 'verified' and proof['record_count'] == 3
    assert proof['input_sha256'] == result['sha256']


@pytest.mark.parametrize('change', ['different_resource', 'filtered_ids', 'duplicate_page', 'omitted_page', 'wrong_count_binding', 'old_version', 'metadata_hash', 'repeated_query_parameter'])
def test_receipt_scope_or_membership_tampering_cannot_grant_completeness(tmp_path, change):
    result, file = export(tmp_path); path = Path(file['receipt_path']); receipt = json.loads(path.read_text())
    if change == 'different_resource': receipt['final_url'] = 'https://source.gov.au/FeatureServer/1'
    elif change == 'filtered_ids': receipt['requests']['initial_ids']['final_url'] = URL + '/query?where=ID%3E1&returnIdsOnly=true&f=json'
    elif change == 'duplicate_page': receipt['pages'][1] = copy.deepcopy(receipt['pages'][0])
    elif change == 'omitted_page': receipt['pages'].pop(); receipt['page_count'] -= 1
    elif change == 'wrong_count_binding': receipt['count_sha256'] = '0' * 64
    elif change == 'old_version': receipt['derivation'] = 'verified_arcgis_all_object_ids_v1'
    elif change == 'metadata_hash': receipt['metadata_sha256'] = '0' * 64
    else: receipt['pages'][0]['final_url'] += '&f=json'
    changed = path.parent / 'changed.json'; changed.write_text(json.dumps(receipt))
    with pytest.raises(ValidationFailure): verify(result, {**file, 'receipt_path': str(changed)}, tmp_path)


def test_input_bytes_and_object_hashes_are_rechecked(tmp_path):
    result, file = export(tmp_path)
    changed = tmp_path / 'changed-input.json'; changed.write_text('{}')
    with pytest.raises(ValidationFailure, match='bytes changed'): verify(result, {**file, 'path': str(changed)}, tmp_path)
    receipt = json.loads(Path(file['receipt_path']).read_text())
    page = Path(file['receipt_path']).parent / 'sha256' / receipt['pages'][0]['sha256']
    page.write_text('{}')
    with pytest.raises(ValidationFailure, match='hash changed'): verify(result, file, tmp_path)


def test_model_flags_and_unscoped_research_cannot_create_a_complete_source_claim(tmp_path):
    result, file = export(tmp_path)
    contract = {'source': {'dataset_url': URL}, 'update': {'mode': 'snapshot', 'complete': True},
                'resources': [{'role': 'crash', 'grain': 'crash', 'file_id': file['id']}]}
    graph = {'nodes': {'metadata': {'url': URL + '?f=pjson', 'document_sha256': result['metadata_sha256']}}}
    grounding = {'applicability': {'roles': {'crash': {'source_url': URL, 'applicable_documents': []}}}}
    assert review_completeness(contract, [file], graph, grounding, root=tmp_path)['resources'][0]['status'] == 'unproven'
    grounding['applicability']['roles']['crash']['applicable_documents'] = ['metadata']
    reviewed = review_completeness(contract, [file], graph, grounding, root=tmp_path)
    assert reviewed['resources'][0]['status'] == 'verified'


def test_snapshot_removal_needs_proof_bound_to_role_grain_resource_and_input(tmp_path):
    result, file = export(tmp_path); proof = verify(result, file, tmp_path)
    previous = {'source': {'dataset_url': URL}, 'resources': [{'role': 'crash', 'grain': 'crash'}]}
    removal = [{'grain': 'crash', 'role': 'crash', 'count': 1}]
    admitted = {'files': [file], 'admission': {'evidence': {'source_completeness': {'version': VERSION,
                 'resources': [{**proof, 'role': 'crash', 'grain': 'crash'}]}}}}
    earlier = '2000-01-01T00:00:00+00:00'
    assert require_removal_authority(previous, admitted, removal, previous_published_at=earlier)['status'] == 'verified_source_membership'
    for key, value in [('role', 'unit'), ('grain', 'observation'), ('source_url', URL + '?where=ID%3E1'), ('input_sha256', '0' * 64)]:
        changed = copy.deepcopy(admitted); changed['admission']['evidence']['source_completeness']['resources'][0][key] = value
        with pytest.raises(NeedsInput) as failure: require_removal_authority(previous, changed, removal, previous_published_at=earlier)
        assert failure.value.details['code'] == 'SOURCE_MEMBERSHIP_UNPROVEN'
    assert require_removal_authority(previous, {}, [], previous_published_at=earlier)['status'] == 'no_records_removed'
    from datetime import timedelta
    from arsia_pipeline.source_completeness import observed_time
    later = observed_time(proof['observed_until']) + timedelta(seconds=1)
    with pytest.raises(NeedsInput): require_removal_authority(previous, admitted, removal, previous_published_at=later)
