import copy
import json
from pathlib import Path

import pytest

from arsia_pipeline.count_semantics import review_count_operations
from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.evidence_grounding import ground_contract
from arsia_pipeline.errors import NeedsInput, UnsupportedCapability, ValidationFailure
from arsia_pipeline.geography_review import review_geography
from arsia_pipeline.lookup_semantics import capability_resources
from arsia_pipeline.trusted_qa import validate_candidate, validate_contract
from test_lookup_evidence import fixture, replace, SOURCE
from test_lookup_qa import candidate, sha
from test_lookup_plan import admitted
from test_lookup_projection import bundle


def counts_fixture(sum_fields=False):
    c, docs, accepted = fixture()
    parent = json.loads(docs['parent']['content_bytes'])
    parent['fields'].extend([
        {'name': 'Deaths', 'description': 'Number of fatalities per crash'},
        {'name': 'Injured', 'description': 'Number of injured persons per crash'},
        {'name': 'Total', 'description': 'Total casualties = Deaths + Injured'},
    ])
    replace(docs, 'parent', parent)
    c['resources'][0]['lookups'][0]['select'].extend(['Deaths', 'Injured'])
    if sum_fields:
        c['resources'][0]['mapping']['casualties'] = {'sum_fields': [{'lookup': 'code', 'field': field} for field in ('Deaths', 'Injured')]}
    else:
        c['resources'][0]['mapping']['fatalities'] = {'field': {'lookup': 'code', 'field': 'Deaths'}}
    accepted['counts'] = [{'document_id': 'parent', 'quote': docs['parent']['text']}]
    return c, docs, accepted


def review(c, docs, accepted):
    graph = build_graph(SOURCE, docs, {'catalogue'})
    grounding = ground_contract(c, docs, accepted, graph=graph)
    assert grounding['ok'], grounding
    return review_count_operations(c, docs, grounding, accepted, graph)


@pytest.mark.parametrize('summed', [False, True])
def test_parent_count_has_explicit_consumer_population_and_scoped_meaning(summed):
    c, docs, accepted = counts_fixture(summed)
    result = review(c, docs, accepted)
    assert result['ok'], result
    assert result['decisions'][0]['role'] == 'codes'
    population = result['lookup_populations'][0]
    assert population['consumer'] == {'role': 'crash', 'grain': 'crash', 'lookup': 'code'}
    assert population['host_allocation_check_required'] is True
    assert all(d['population'] == 'crash' for d in population['decisions'])


@pytest.mark.parametrize('definition', ['Number of fatalities', 'Number of fatalities for a unit involved in a road crash',
                                      'Number of fatalities per year', 'Fatal indicator, 0 or 1'])
def test_lookup_count_does_not_infer_parent_population(definition):
    c, docs, accepted = counts_fixture()
    parent = json.loads(docs['parent']['content_bytes'])
    parent['fields'][4]['description'] = definition
    replace(docs, 'parent', parent)
    accepted['counts'][0]['quote'] = docs['parent']['text']
    result = review(c, docs, accepted)
    assert not result['ok']
    assert any(i['code'].startswith('LOOKUP_COUNT_POPULATION_') for i in result['issues'])


def test_child_count_definition_cannot_override_parent_population():
    c, docs, accepted = counts_fixture()
    parent = json.loads(docs['parent']['content_bytes'])
    parent['fields'][4]['description'] = 'Number of fatalities'
    replace(docs, 'parent', parent)
    child = json.loads(docs['child']['content_bytes'])
    child['fields'].append({'name': 'Deaths', 'description': 'Number of fatalities per crash'})
    replace(docs, 'child', child)
    accepted['counts'] = [{'document_id': k, 'quote': docs[k]['text']} for k in ('child', 'parent')]
    assert not review(c, docs, accepted)['ok']


def test_uncited_conflicting_population_definition_remains_blocking():
    c, docs, accepted = counts_fixture()
    parent = json.loads(docs['parent']['content_bytes'])
    parent['fields'][4]['definition'] = 'Number of fatalities for a unit involved in a road crash'
    replace(docs, 'parent', parent)
    result = review(c, docs, accepted)
    assert any(i['code'] == 'LOOKUP_COUNT_POPULATION_CONFLICT' for i in result['issues'])


def test_mixed_resource_sum_is_diagnosed_without_coercing_dictionary_to_field_name():
    c, docs, accepted = counts_fixture(True)
    c['resources'][0]['mapping']['casualties']['sum_fields'][1] = 'Injured'
    child = json.loads(docs['child']['content_bytes'])
    child['fields'].append({'name': 'Injured', 'description': 'Number of injured persons per crash'})
    replace(docs, 'child', child)
    accepted['counts'].append({'document_id': 'child', 'quote': docs['child']['text']})
    result = review(c, docs, accepted)
    assert not result['ok']
    assert result['issues'][0]['code'] == 'LOOKUP_CROSS_RESOURCE_SUM_UNSUPPORTED'


def test_independently_matched_rows_in_same_parent_are_not_one_population():
    c, docs, accepted = counts_fixture(True)
    c['resources'][0]['lookups'].append({**c['resources'][0]['lookups'][0], 'name': 'other'})
    c['resources'][0]['mapping']['casualties']['sum_fields'][1]['lookup'] = 'other'
    assert review(c, docs, accepted)['issues'][0]['code'] == 'LOOKUP_CROSS_RESOURCE_SUM_UNSUPPORTED'


@pytest.mark.parametrize('mode', ['sample', 'full'])
@pytest.mark.parametrize('value', ['2', '0', ''])
def test_parent_count_broadcast_is_rejected_even_if_zero_or_unknown(tmp_path, mode, value):
    def configure(c, files):
        child = Path(files[0]['path']); child.write_text(child.read_text().replace(',B,1', ',A,1'))
        parent = Path(files[1]['path']); parent.write_text(parent.read_text().replace('A,F,2,', 'A,' + ('U' if value=='0' else 'F') + ',' + value + ','))
        for f in files: f.update(sha256=sha(f['path']), size=Path(f['path']).stat().st_size)
    c, files, run = candidate(tmp_path, mode, configure)
    with pytest.raises(ValidationFailure) as error: validate_candidate(run, c, files, 'fixture', tmp_path)
    assert error.value.qa[0]['code'] == 'LOOKUP_COUNT_BROADCAST'
    assert not list(tmp_path.glob('trusted-lookup-replay-*.json'))


def test_same_parent_can_supply_multiple_fields_for_one_consumer_count(tmp_path):
    c, files, run = candidate(tmp_path)
    with pytest.raises(NeedsInput) as error: validate_candidate(run, c, files, 'fixture', tmp_path)
    assert error.value.details['lookup_replay']['row_equality_verified'] is True


def test_full_qa_detects_broadcast_beyond_child_sample(tmp_path):
    def configure(c, files):
        child = Path(files[0]['path'])
        parent = Path(files[1]['path'])
        child.write_text('ID,DATE,Type,INJURED\n' + ''.join(
            f'{i:04d},30/04/2024 13:20,K{i if i < 1000 else 0},0\n' for i in range(1001)))
        parent.write_text('Code,Class,Deaths,X,Y\n' + ''.join(
            f'K{i},F,1,149.1,-35.2\n' for i in range(1000)))
        for f in files:
            f.update(sha256=sha(f['path']), size=Path(f['path']).stat().st_size)
    for mode in ('sample', 'full'):
        root = tmp_path / mode
        root.mkdir()
        c, files, run = candidate(root, mode, configure)
        if mode == 'sample':
            with pytest.raises(NeedsInput) as error:
                validate_candidate(run, c, files, 'fixture', root)
            replay = error.value.details['lookup_replay']
            assert replay['fact_rows'] == {'crash': 1000}
            assert replay['admission'] is False
        else:
            with pytest.raises(ValidationFailure) as error:
                validate_candidate(run, c, files, 'fixture', root)
            assert error.value.qa[0]['code'] == 'LOOKUP_COUNT_BROADCAST'
            assert not list(root.glob('trusted-lookup-replay-*.json'))


def test_category_only_lookup_can_be_shared_without_count_broadcast(tmp_path):
    def configure(c, files):
        for metric in ('fatalities', 'casualties'):c['resources'][0]['mapping'].pop(metric)
        path = Path(files[0]['path']);path.write_text(path.read_text().replace(',B,1', ',A,1'))
        files[0].update(sha256=sha(path), size=path.stat().st_size)
    c, files, run = candidate(tmp_path, configure=configure)
    with pytest.raises(NeedsInput) as error: validate_candidate(run, c, files, 'fixture', tmp_path)
    assert error.value.details['lookup_replay']['row_equality_verified'] is True


def test_allocation_guard_is_shared_across_independently_named_lookups(tmp_path):
    def configure(c, files):
        path = Path(files[0]['path'])
        path.write_text('ID,DATE,Type,Other,INJURED\n001,30/04/2024 13:20,A,B,3\n002,01/05/2024 13:20,B,A,1\n')
        files[0].update(sha256=sha(path), size=path.stat().st_size)
        r = c['resources'][0]
        r['lookups'].append({**r['lookups'][0], 'name':'other', 'fields':['Other']})
        r['mapping']['casualties'] = {'sum_fields':[{'lookup':name,'field':'Deaths'} for name in ('code','other')]}
    c, files, run = candidate(tmp_path, 'full', configure)
    with pytest.raises(ValidationFailure) as error: validate_candidate(run,c,files,'fixture',tmp_path)
    assert error.value.qa[0]['code'] == 'LOOKUP_COUNT_BROADCAST'


def geometry_bundle(tmp_path, *, geometry_type='Point', mapped=True, wrong_crs=False):
    c, files = bundle(tmp_path)
    props = {'Code': 'A', 'Class': 'F', 'Deaths': '2'}
    coords = [149.1, -35.2] if geometry_type == 'Point' else [[[149.1,-35.2],[149.2,-35.2],[149.2,-35.3],[149.1,-35.2]]]
    parent = admitted(tmp_path, 'codes.geojson', json.dumps({'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'properties': props, 'geometry': {'type': geometry_type, 'coordinates': coords}}]}))
    files[1] = parent;c['lookup_tables'][0]['file_id'] = parent['id']
    r = c['resources'][0]
    r['lookups'][0]['select'] = ['Class', 'Deaths'] + (['__geometry_x', '__geometry_y'] if mapped else [])
    if mapped:
        r['mapping']['geography'] = {'x_field': {'lookup':'code','field':'__geometry_x'},
            'y_field': {'lookup':'code','field':'__geometry_y'}, 'crs': 'EPSG:3857' if wrong_crs else 'EPSG:4326'}
    else:r['mapping'].pop('geography')
    return c, files


def test_lookup_projected_geometry_checks_its_own_physical_crs(tmp_path):
    c, files = geometry_bundle(tmp_path, wrong_crs=True)
    with pytest.raises(NeedsInput) as error: validate_contract(c, files)
    assert error.value.details['blockers'][0]['code'] == 'GEOMETRY_CRS_CONFLICT'


def test_explicit_parent_point_projection_has_a_valid_physical_plan(tmp_path):
    c, files = geometry_bundle(tmp_path)
    assert set(validate_contract(c, files)) == {'crash'}


@pytest.mark.parametrize('kind', ['Point', 'Polygon'])
def test_unprojected_codebook_geometry_is_not_promoted_to_crash_location(tmp_path, kind):
    c, files = geometry_bundle(tmp_path, geometry_type=kind, mapped=False)
    assert set(validate_contract(c, files)) == {'crash'}
    parent = next(r for r in capability_resources(c) if r['role'] == 'codes')
    assert parent['grain'] == 'lookup' and not parent['mapping']


def test_parent_projection_cannot_hide_existing_child_point_geometry(tmp_path):
    c, files = geometry_bundle(tmp_path)
    child = admitted(tmp_path, 'child.geojson', json.dumps({'type':'FeatureCollection','features':[
        {'type':'Feature','properties':{'ID':'001','DATE':'30/04/2024 13:20','Type':'A','INJURED':'3'},
         'geometry':{'type':'Point','coordinates':[149.3,-35.4]}}]}))
    files[0] = child;c['resources'][0].update(file_id=child['id'],table={})
    with pytest.raises(NeedsInput) as error: validate_contract(c, files)
    assert error.value.details['blockers'][0]['code'] == 'GEOGRAPHY_MAPPING_MISSING'


def test_documented_child_csv_coordinates_still_trigger_omission_review():
    c, docs, accepted = fixture()
    docs['child_geo'] = {'url':'https://cdn.example/child-geo.txt','text':'Longitude and Latitude coordinates use EPSG:4326.'}
    graph = build_graph(SOURCE, {k:v for k,v in docs.items() if k!='child_geo'}, {'catalogue'})
    grounding = ground_contract(c, docs, accepted, graph=graph)
    grounding['applicability']['roles']['crash']['applicable_documents'].append('child_geo')
    views = capability_resources(c)
    result = review_geography({**c,'resources':views},docs,grounding,{'crash':['ID','Longitude','Latitude'],'codes':['Code','X','Y']})
    assert not result['ok'] and result['issues'][0]['role'] == 'crash'
