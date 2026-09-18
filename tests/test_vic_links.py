"""Small counterexamples for the Person/Node source review."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def sample():
    return {
        'accident': [
            {'ACCIDENT_NO': '0001', 'ACCIDENT_DATE': '2020-01-01', 'NODE_ID': 'N1',
             'NO_OF_VEHICLES': '1', 'NO_PERSONS': '2', 'NO_PERSONS_KILLED': '0',
             'NO_PERSONS_INJ_2': '0', 'NO_PERSONS_INJ_3': '1', 'NO_PERSONS_NOT_INJ': '1'},
            {'ACCIDENT_NO': '0002', 'ACCIDENT_DATE': '2015-01-01', 'NODE_ID': 'N2',
             'NO_OF_VEHICLES': '0', 'NO_PERSONS': '1', 'NO_PERSONS_KILLED': '0',
             'NO_PERSONS_INJ_2': '0', 'NO_PERSONS_INJ_3': '1', 'NO_PERSONS_NOT_INJ': '0'}],
        'vehicle': [{'ACCIDENT_NO': '0001', 'VEHICLE_ID': 'A', 'VEHICLE_TYPE': '21'}],
        'person': [
            {'ACCIDENT_NO': '0001', 'PERSON_ID': 'A', 'VEHICLE_ID': 'A', 'ROAD_USER_TYPE': '16', 'INJ_LEVEL': '4'},
            {'ACCIDENT_NO': '0001', 'PERSON_ID': '01', 'VEHICLE_ID': '', 'ROAD_USER_TYPE': '1', 'INJ_LEVEL': '3'},
            {'ACCIDENT_NO': '0002', 'PERSON_ID': '01', 'VEHICLE_ID': '', 'ROAD_USER_TYPE': '9', 'INJ_LEVEL': '3'}],
        'node': [
            {'ACCIDENT_NO': '0001', 'NODE_ID': 'N1', 'LATITUDE': '-37.8', 'LONGITUDE': '144.9', 'DEG_URBAN_NAME': 'X'},
            {'ACCIDENT_NO': '0001', 'NODE_ID': 'N1', 'LATITUDE': '-37.8', 'LONGITUDE': '144.9', 'DEG_URBAN_NAME': 'X'},
            {'ACCIDENT_NO': '0001', 'NODE_ID': 'N1', 'LATITUDE': '-37.8000', 'LONGITUDE': '144.9000', 'DEG_URBAN_NAME': 'Y'}]}


def save(directory, records):
    config = {'resources': []}
    template = json.loads((ROOT / 'config/native-inputs.json').read_text())
    for spec in template['resources']:
        name = spec['resource_id'].removeprefix('official_vic_')
        if name not in records:
            continue
        target = directory / f'{name}.csv'
        with target.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=spec['header'])
            writer.writeheader()
            writer.writerows(records[name])
        config['resources'].append({**spec, 'path': target.name,
            'expected_sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    target = directory / 'config.json'
    target.write_text(json.dumps(config))
    return target


def run(config, output):
    return subprocess.run([sys.executable, str(ROOT / 'tools/review_vic_links.py'),
                           '--config', str(config), '--output', str(output)], capture_output=True, text=True)


def test_review_distinguishes_exact_duplicates_from_coordinate_equivalence(tmp_path):
    config = save(tmp_path, sample())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    output = tmp_path / 'result.json'
    result = run(config, output)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report['inputs_unchanged']
    assert report['node']['matching_groups'] == 1
    assert report['node']['exact_duplicate_extra_rows'] == 1
    assert report['node']['coordinate_conflicts'] == []
    assert report['node']['missing_scope_counts'] == {'outside_2020-2024': 1}
    assert report['person']['blank_nonpedestrian_scope_counts'] == {'outside_2020-2024': 1}
    assert report['person']['unmatched'] == []
    assert report['person']['type16']['linked_vehicle_type_counts'] == {'21': 1}
    assert report['count_differences'] == {'vehicle': [], 'person': [], 'injury_components': []}
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p != output}
    assert run(config, output).returncode != 0


def test_review_exposes_unmatched_references_and_count_context(tmp_path):
    rows = sample()
    rows['person'][0].update(VEHICLE_ID='B', ROAD_USER_TYPE='2')
    rows['accident'][0]['NO_PERSONS'] = '3'
    rows['accident'][1]['NO_OF_VEHICLES'] = ''
    rows['node'][2]['LATITUDE'] = '-37.80000001'
    rows['node'].append({'ACCIDENT_NO': '0002', 'NODE_ID': 'N2', 'LATITUDE': 'NaN', 'LONGITUDE': '144.9'})
    output = tmp_path / 'result.json'
    result = run(save(tmp_path, rows), output)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text())
    assert report['person']['unmatched_scope_counts'] == {'2020-2024': 1}
    assert report['person']['unmatched'][0]['row_locator'] == 'csv:1'
    assert report['person']['unmatched'][0]['VEHICLE_ID'] == 'B'
    assert report['count_differences']['person'][0]['observed'] == 2
    assert report['count_differences']['vehicle'] == []
    assert len(report['node']['coordinate_conflicts']) == 1
    assert len(report['node']['invalid_coordinates']) == 1


@pytest.mark.parametrize('problem', ['changed_hash', 'duplicate_key'])
def test_review_rejects_untrusted_or_ambiguous_inputs(tmp_path, problem):
    records = sample()
    if problem == 'duplicate_key':
        records['accident'].append(dict(records['accident'][0]))
    config = save(tmp_path, records)
    if problem == 'changed_hash':
        with (tmp_path / 'person.csv').open('ab') as stream:
            stream.write(b'\n')
    output = tmp_path / 'result.json'
    result = run(config, output)
    assert result.returncode != 0
    assert not output.exists()
    assert ('hash does not match' if problem == 'changed_hash' else 'Duplicate accident key') in result.stderr


@pytest.mark.parametrize('problem', [None, 'changed_response', 'truncated_response'])
def test_saved_api_comparison(tmp_path, problem):
    records = sample()
    records['person'][0]['VEHICLE_ID'] = 'B'
    for row in records['node']:
        row.update(AMG_X='0', AMG_Y='0')
    config = save(tmp_path, records)
    review = tmp_path / 'review.json'
    assert run(config, review).returncode == 0
    requests = []
    for spec in json.loads(config.read_text())['resources']:
        name = spec['resource_id'].removeprefix('official_vic_')
        api_rows = [{'_id': 9000+i, **{f: row.get(f) or None for f in spec['header']}}
                    for i, row in enumerate(records[name])]
        if name == 'node':
            api_rows.pop()  # Removing a distinct observation must be detected.
        if name == 'accident':
            api_rows[0]['NO_PERSONS'] = '3'
        raw = json.dumps({'success': True, 'result': {'records': api_rows,
            'total': len(api_rows) + (1 if problem == 'truncated_response' else 0), 'total_was_estimated': False}})
        requests.append({'label': name + '_cases', 'parameters': {'filters': json.dumps({'ACCIDENT_NO': ['0001', '0002']})},
                         'response_raw_utf8': raw, 'response_bytes': len(raw.encode()),
                         'response_sha256': hashlib.sha256(raw.encode()).hexdigest()})
    flat_raw = json.dumps({'success': True, 'result': {'records': [{'ACCIDENT_NO': '0001', '_id': 4,
        'LATITUDE': '-37.800', 'LONGITUDE': '144.9', 'VICGRID_X': '0', 'VICGRID_Y': '0'}], 'total': 1}})
    requests.append({'label': 'flat_cases', 'parameters': {'filters': json.dumps({'ACCIDENT_NO': ['0001']})},
                     'response_raw_utf8': flat_raw, 'response_bytes': len(flat_raw.encode()),
                     'response_sha256': hashlib.sha256(flat_raw.encode()).hexdigest()})
    if problem == 'changed_response':
        requests[0]['response_raw_utf8'] += ' '
    api = tmp_path / 'api.json'
    api.write_text(json.dumps({'local_review_sha256': hashlib.sha256(review.read_bytes()).hexdigest(), 'requests': requests}))
    output = tmp_path / 'comparison.json'
    result = subprocess.run([sys.executable, str(ROOT / 'tools/compare_vic_evidence.py'), '--config', str(config),
        '--review', str(review), '--api-evidence', str(api), '--output', str(output)], capture_output=True, text=True)
    if problem:
        assert result.returncode != 0
        assert not output.exists()
        assert ('has changed' if problem == 'changed_response' else 'Incomplete') in result.stderr
        return
    assert result.returncode == 0, result.stderr
    data = json.loads(output.read_text())
    assert data['inputs_unchanged']
    assert data['native_field_comparisons']['person']['local_only'] == []
    assert data['native_field_comparisons']['accident']['api_only'][0]['row']['NO_PERSONS'] == '3'
    assert data['native_field_comparisons']['node']['local_only']
    assert data['original_unmatched_references'][0]['api_person_id'] == 9000
    assert data['original_unmatched_references'][0]['csv_row_locator'] == 'csv:1'
    assert data['original_unmatched_references'][0]['vehicle_still_absent']
    assert data['original_missing_node_cases'][0]['still_absent']
    assert data['node_and_flat_coordinates'][0]['all_selected_values_numerically_equal']
