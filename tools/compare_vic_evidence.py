"""Compare saved DataStore responses with the pinned VIC CSVs, without network access."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from profile_vic_inputs import COUNTS, KEYS, native_rows, sha256


ROOT = Path(__file__).resolve().parents[1]


def read_responses(path):
    envelope = json.loads(Path(path).read_text())
    responses, selected = {}, {}
    for request in envelope['requests']:
        raw = request['response_raw_utf8'].encode('utf-8')
        if len(raw) != request['response_bytes'] or hashlib.sha256(raw).hexdigest() != request['response_sha256']:
            raise ValueError('Saved API response has changed')
        data = json.loads(raw)
        if data.get('success') is not True:
            raise ValueError('Unsuccessful API response')
        label, result = request['label'], data['result']
        if label in responses:
            raise ValueError('Repeated response label')
        responses[label] = result
        if label == 'current_package':
            continue
        ids = set(json.loads(request['parameters']['filters'])['ACCIDENT_NO'])
        if result.get('total_was_estimated') or len(result['records']) != result['total']:
            raise ValueError('Incomplete API result')
        if any(row['ACCIDENT_NO'] not in ids for row in result['records']):
            raise ValueError('API row outside requested cases')
        selected[label] = ids
    return envelope, responses, selected


def compare(config_path, review_path, api_path):
    config_path, review_path, api_path = map(Path, (config_path, review_path, api_path))
    review = json.loads(review_path.read_text())
    envelope, responses, selected = read_responses(api_path)
    if envelope['local_review_sha256'] != sha256(review_path):
        raise ValueError('Local review does not match the API case selection')
    specs = {r['resource_id'].removeprefix('official_vic_'): r for r in
             json.loads(config_path.read_text())['resources'] if r['resource_id'].startswith('official_vic_')}
    paths, local, checks = {}, {}, {}
    for name in KEYS:
        spec = specs[name]
        paths[name] = (config_path.parent / spec['path']).resolve()
        if sha256(paths[name]) != spec['expected_sha256'] or spec['expected_sha256'] != review['inputs'][name]['file_sha256']:
            raise ValueError(f'Input hash does not match: {name}')
        wanted = selected[name + '_cases'] | (selected['flat_cases'] if name == 'node' else set())
        local[name] = [(loc, row) for loc, row in native_rows(paths[name], spec['header']) if row['ACCIDENT_NO'] in wanted]
        header = spec['header']

        def values(row):
            # Only API null and CSV empty text are treated as equivalent here.
            return tuple('' if row[f] is None else str(row[f]) for f in header)

        api_rows = responses[name + '_cases']['records']
        local_rows = [(loc, row) for loc, row in local[name] if row['ACCIDENT_NO'] in selected[name + '_cases']]
        before, after = Counter(values(r) for _, r in local_rows), Counter(values(r) for r in api_rows)
        checks[name] = {'selected_accidents': len(selected[name + '_cases']),
            'local_rows': len(local_rows), 'api_rows': len(api_rows),
            'local_only': [{'row': dict(zip(header, r)), 'count': n} for r, n in (before-after).items()],
            'api_only': [{'row': dict(zip(header, r)), 'count': n} for r, n in (after-before).items()]}

    current = {name: responses[name + '_cases']['records'] for name in KEYS}
    vehicles = {(r['ACCIDENT_NO'], r['VEHICLE_ID']) for r in current['vehicle']}
    person_keys = {(r['ACCIDENT_NO'], r['PERSON_ID']): r for r in current['person']}
    references = []
    for row in review['person']['unmatched']:
        key = row['accident_no']
        if key not in selected['person_cases'] or key not in selected['vehicle_cases']:
            raise ValueError('Unmatched case was not queried in both child resources')
        person = person_keys.get((key, row['PERSON_ID']))
        references.append({'accident_no': key, 'person_id': row['PERSON_ID'],
            'csv_row_locator': row['row_locator'], 'api_person_id': person['_id'] if person else None,
            'reference_unchanged': person is not None and person['VEHICLE_ID'] == row['VEHICLE_ID'],
            'vehicle_still_absent': (key, row['VEHICLE_ID']) not in vehicles})

    counts = {'vehicle': Counter(r['ACCIDENT_NO'] for r in current['vehicle']),
              'person': Counter(r['ACCIDENT_NO'] for r in current['person'])}
    injuries = defaultdict(Counter)
    for r in current['person']:
        injuries[r['ACCIDENT_NO']][r['INJ_LEVEL']] += 1
    count_checks = []
    for r in current['accident']:
        key, differences = r['ACCIDENT_NO'], {}
        if key not in selected['person_cases'] or key not in selected['vehicle_cases']:
            raise ValueError('Accident case lacks a complete child query')
        for field, observed in [('NO_OF_VEHICLES', counts['vehicle'][key]), ('NO_PERSONS', counts['person'][key]),
                                *((field, injuries[key][code]) for code, field in zip('1234', COUNTS[1:5]))]:
            if r[field] is not None and str(observed) != r[field]:
                differences[field] = {'api_accident_declared': r[field], 'api_child_observed': observed}
        if differences:
            count_checks.append({'accident_no': key, 'api_accident_id': r['_id'], 'differences': differences})

    node_ids = {r['ACCIDENT_NO'] for r in current['node']}
    missing = []
    for r in review['node']['missing_matches']:
        key = r['accident_no']
        if key not in selected['node_cases']:
            raise ValueError('Missing Node case was not queried')
        missing.append({'accident_no': key, 'node_id': r['accident']['NODE_ID'], 'still_absent': key not in node_ids})
    flat = []
    for r in responses['flat_cases']['records']:
        matched = [(loc, n) for loc, n in local['node'] if n['ACCIDENT_NO'] == r['ACCIDENT_NO']]
        fields = (('LATITUDE', 'LATITUDE'), ('LONGITUDE', 'LONGITUDE'), ('AMG_X', 'VICGRID_X'), ('AMG_Y', 'VICGRID_Y'))
        flat.append({'accident_no': r['ACCIDENT_NO'], 'api_flat_id': r['_id'],
            'node_row_locators': [loc for loc, _ in matched],
            'node_values': [dict(zip((a for a, _ in fields), v)) for v in sorted({tuple(n[a] for a, _ in fields) for _, n in matched})],
            'flat_values': {b: r[b] for _, b in fields},
            'all_selected_values_numerically_equal': bool(matched) and all(Decimal(n[a]) == Decimal(r[b]) for _, n in matched for a, b in fields)})

    unchanged = all(sha256(paths[name]) == specs[name]['expected_sha256'] for name in KEYS)
    if not unchanged:
        raise ValueError('Inputs changed during comparison')
    return {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Only the saved API selections; this is not a current full-release validation or a CRS transformation',
        'evidence_sha256': {p.name: sha256(p) for p in (config_path, review_path, api_path, Path(__file__))},
        'native_field_comparisons': checks, 'original_unmatched_references': references,
        'current_api_count_differences': count_checks, 'original_missing_node_cases': missing,
        'node_and_flat_coordinates': flat, 'inputs_unchanged': unchanged}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/native-inputs.json')
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--api-evidence', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new filename.')
    try:
        result = compare(args.config, args.review, args.api_evidence)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Cannot compare VIC evidence: {exc}\n')
    print(f'Comparison saved: {args.output}')


if __name__ == '__main__':
    main()
