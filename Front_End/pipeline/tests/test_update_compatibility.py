import copy

import pytest

from arsia_pipeline.errors import NeedsInput
from arsia_pipeline.update_compatibility import require_compatible_update


def contract():
    return {"resources":[{"role":"crashes","grain":"crash","key":["year","id"],"file_id":"old-upload","mapping":{"fatalities":"old_field"}},
                         {"role":"units","grain":"unit","key":["year","id","unit"]}],
            "relations":[{"child":"units","parent":"crashes","fields":["year","id"]}]}


@pytest.mark.parametrize("mode",["partition","incremental"])
@pytest.mark.parametrize("change",["role","grain","key_order","key_field","removed_role","relation"])
def test_retained_history_refuses_identity_drift(mode,change):
    previous = contract()
    candidate = copy.deepcopy(previous)
    if change == "role": candidate["resources"][0]["role"] = "new_crash_role"
    elif change == "grain": candidate["resources"][0]["grain"] = "observation"
    elif change == "key_order": candidate["resources"][0]["key"].reverse()
    elif change == "key_field": candidate["resources"][0]["key"] = ["new_id"]
    elif change == "removed_role": candidate["resources"].pop()
    elif change == "relation": candidate["relations"][0]["fields"] = ["year","different_id"]
    with pytest.raises(NeedsInput,match="incompatible record identities") as error:
        require_compatible_update(previous,candidate,mode)
    assert error.value.details["required_transition"] == "complete_snapshot"


def test_reupload_new_order_and_file_id_can_compose():
    previous = contract()
    candidate = copy.deepcopy(previous)
    candidate["resources"][0].update(file_id="new-upload")
    candidate["resources"].reverse()
    require_compatible_update(previous,candidate,"partition")
    require_compatible_update(previous,candidate,"incremental")


def test_full_snapshot_may_rekey_but_absent_previous_contract_cannot_compose():
    candidate = contract()
    candidate["resources"][0]["key"] = ["new_key"]
    require_compatible_update(contract(),candidate,"snapshot")
    with pytest.raises(NeedsInput,match="no admitted identity contract"):
        require_compatible_update({},candidate,"incremental")


@pytest.mark.parametrize('mode', ['partition', 'incremental'])
@pytest.mark.parametrize('change', ['count_field', 'sum_operand', 'date', 'timezone', 'severity', 'crs', 'nulls', 'population', 'jurisdiction'])
def test_retained_history_refuses_unproven_semantic_changes(mode, change):
    previous = contract()
    mapping = previous['resources'][0]['mapping']
    mapping.update(fatalities={'field': 'deaths'}, casualties={'sum_fields': ['deaths', 'injuries']},
                   date={'field': 'occurred', 'formats': ['%Y-%m-%d'], 'timezone': 'Australia/Sydney'},
                   severity={'field': 'severity', 'categories': {'fatal': {'code': 'fatal', 'label': 'Fatal', 'is_fatal_crash': True}}},
                   geography={'x_field': 'x', 'y_field': 'y', 'crs': 'EPSG:4326'})
    candidate = copy.deepcopy(previous)
    proposed = candidate['resources'][0]['mapping']
    if change == 'count_field': proposed['fatalities']['field'] = 'injuries'
    elif change == 'sum_operand': proposed['casualties']['sum_fields'].append('deaths')
    elif change == 'date': proposed['date']['field'] = 'reported'
    elif change == 'timezone': proposed['date']['timezone'] = 'UTC'
    elif change == 'severity': proposed['severity']['categories']['fatal']['is_fatal_crash'] = False
    elif change == 'crs': proposed['geography']['crs'] = 'EPSG:4283'
    elif change == 'nulls': candidate['null_values'] = [0]
    elif change == 'population': candidate['definitions'] = {'casualties_includes_fatalities': False}
    elif change == 'jurisdiction': candidate['source'] = {'jurisdiction': ['NT']}
    candidate['semantic_compatibility'] = {'confirmed': True, 'approved_by': 'model'}
    with pytest.raises(NeedsInput, match='Semantic compatibility') as failure:
        require_compatible_update(previous, candidate, mode)
    assert failure.value.details['code'] == 'UPDATE_SEMANTICS_UNPROVEN'
    require_compatible_update(previous, candidate, 'snapshot')


def test_equivalent_ordering_does_not_block_an_update():
    previous = contract()
    previous.update(null_values=['NA', -1], definitions={'casualties_includes_fatalities': True})
    previous['resources'][0]['mapping'] = {'date': {'field': 'date', 'formats': ['%Y-%m-%d', '%d/%m/%Y']},
                                           'casualties': {'sum_fields': ['injuries', 'deaths']}}
    candidate = copy.deepcopy(previous)
    candidate['resources'][0]['mapping']['date']['formats'].reverse()
    candidate['resources'][0]['mapping']['casualties']['sum_fields'].reverse()
    candidate['null_values'].reverse()
    candidate['source'] = {'coverage': {'from': '2025-01-01', 'to': '2025-12-31'}, 'title': 'New export'}
    require_compatible_update(previous, candidate, 'incremental')


def test_official_definition_change_is_detected_with_unchanged_mapping():
    contract_value = contract()
    old = {'evidence': {'grounding': {'field_bindings': [{'role': 'crashes', 'claim': 'counts', 'field': 'old_field',
           'evidence': [{'document_id': 'old', 'mode': 'official_structured_field', 'official_field': 'persons', 'description': 'Deaths within 30 days'}]}]}}}
    new = copy.deepcopy(old)
    fact = new['evidence']['grounding']['field_bindings'][0]['evidence'][0]
    fact['document_id'] = 'new-fetch'
    fact['schema_pointer'] = '/columns/12'
    require_compatible_update(contract_value, contract_value, 'partition', previous_admission=old, candidate_admission=new)
    fact['description'] = 'Deaths at the scene only'
    with pytest.raises(NeedsInput) as failure:
        require_compatible_update(contract_value, contract_value, 'partition', previous_admission=old, candidate_admission=new)
    assert failure.value.details['changed_components'] == ['official_field_definitions']


def test_dropping_structured_grounding_does_not_hide_known_definition_change():
    previous = {'evidence': {'grounding': {'field_bindings': []}}}
    with pytest.raises(NeedsInput):
        require_compatible_update(contract(), contract(), 'partition', previous_admission=previous, candidate_admission={})
