"""Inspect Person and Node relationships in the pinned VIC files."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from profile_vic_inputs import COUNTS, KEYS, native_rows, nonnegative_integer, sha256


ROOT = Path(__file__).resolve().parents[1]
PERSON_FIELDS = ('PERSON_ID', 'VEHICLE_ID', 'ROAD_USER_TYPE', 'ROAD_USER_TYPE_DESC',
                 'INJ_LEVEL', 'SEATING_POSITION')
VEHICLE_FIELDS = ('VEHICLE_ID', 'VEHICLE_TYPE', 'VEHICLE_TYPE_DESC',
                  'TOTAL_NO_OCCUPANTS', 'VEHICLE_DCA_CODE', 'TRAILER_TYPE')


def review(config_path):
    config_path = Path(config_path).resolve()
    specs = {r['resource_id'].removeprefix('official_vic_'): r for r in
             json.loads(config_path.read_text())['resources']
             if r['resource_id'].startswith('official_vic_')}
    inputs, paths = {}, {}
    for name in KEYS:
        spec = specs[name]
        paths[name] = (config_path.parent / spec['path']).resolve()
        checksum = sha256(paths[name])
        if checksum != spec['expected_sha256']:
            raise ValueError(f'Input hash does not match: {name}')
        inputs[name] = {'file_sha256': checksum, 'rows': 0}

    def rows(name):
        seen = set()
        for locator, row in native_rows(paths[name], specs[name]['header']):
            key = tuple(row[f] for f in KEYS[name])
            if any(not value.strip() for value in key):
                raise ValueError(f'Blank {name} key at {locator}')
            if name != 'node' and key in seen:
                raise ValueError(f'Duplicate {name} key at {locator}')
            seen.add(key)
            inputs[name]['rows'] += 1
            yield locator, row

    crashes = {r['ACCIDENT_NO']: {'row_locator': loc, **r} for loc, r in rows('accident')}

    def scope(key):
        if key not in crashes:
            return 'no_parent'
        # Dates are checked before using their year in any scope counts.
        year = datetime.strptime(crashes[key]['ACCIDENT_DATE'], '%Y-%m-%d').year
        return '2020-2024' if 2020 <= year <= 2024 else 'outside_2020-2024'

    scopes = {key: scope(key) for key in crashes}
    vehicles, persons = defaultdict(list), defaultdict(list)
    vehicle_keys = set()
    type21, type16 = [], []
    for loc, r in rows('vehicle'):
        key = r['ACCIDENT_NO']
        entry = {'row_locator': loc, **{f: r[f] for f in VEHICLE_FIELDS}}
        vehicles[key].append(entry)
        vehicle_keys.add((key, r['VEHICLE_ID']))
        if r['VEHICLE_TYPE'] == '21':
            type21.append({'accident_no': key, **entry})

    reference_counts, injury_counts = Counter(), defaultdict(Counter)
    unmatched, blank_other, pedestrian_linked = [], [], []
    all_person_ids_numeric = Counter()
    for loc, r in rows('person'):
        key, vehicle = r['ACCIDENT_NO'], r['VEHICLE_ID']
        entry = {'row_locator': loc, **{f: r[f] for f in PERSON_FIELDS}}
        persons[key].append(entry)
        injury_counts[key][r['INJ_LEVEL']] += 1
        reference = 'blank' if not vehicle.strip() else (
            'matched' if (key, vehicle) in vehicle_keys else 'unmatched')
        reference_counts[(r['ROAD_USER_TYPE'], r['ROAD_USER_TYPE_DESC'],
                          scopes.get(key, 'no_parent'), reference)] += 1
        if reference == 'unmatched':
            unmatched.append({'accident_no': key, **entry})
        if reference == 'blank' and r['ROAD_USER_TYPE'] != '1':
            blank_other.append({'accident_no': key, **entry})
        if reference != 'blank' and r['ROAD_USER_TYPE'] == '1':
            pedestrian_linked.append({'accident_no': key, **entry})
        if r['ROAD_USER_TYPE'] == '16':
            type16.append({'accident_no': key, **entry})
        if r['PERSON_ID'].isdigit():
            all_person_ids_numeric[r['ROAD_USER_TYPE']] += 1

    def context(key):
        r = crashes.get(key)
        return {'accident_no': key, 'scope': scopes.get(key, 'no_parent'),
                'accident': ({f: r[f] for f in ('row_locator', 'ACCIDENT_DATE', 'NODE_ID',
                    'POLICE_ATTEND', 'SEVERITY', *COUNTS)} if r else None),
                'vehicles': vehicles[key], 'persons': persons[key]}

    count_differences = {'vehicle': [], 'person': [], 'injury_components': []}
    for key, r in crashes.items():
        for name, field, actual in (('vehicle', 'NO_OF_VEHICLES', len(vehicles[key])),
                                     ('person', 'NO_PERSONS', len(persons[key]))):
            declared = nonnegative_integer(r[field])
            if declared is not None and declared != actual:
                count_differences[name].append({'declared': declared, 'observed': actual, **context(key)})
        delta = {}
        for code, field in zip('1234', COUNTS[1:5]):
            declared = nonnegative_integer(r[field])
            actual = injury_counts[key][code]
            if declared is not None and declared != actual:
                delta[field] = {'declared': declared, 'observed': actual}
        if delta:
            count_differences['injury_components'].append({'differences': delta, **context(key)})

    node_groups = defaultdict(list)
    by_node = defaultdict(set)
    for loc, r in rows('node'):
        key = (r['ACCIDENT_NO'], r['NODE_ID'])
        node_groups[key].append({'row_locator': loc, **r})
        by_node[r['NODE_ID']].add(r['ACCIDENT_NO'])
    multiplicity, varying_fields = Counter(), Counter()
    exact_extra = 0
    coordinate_conflicts, invalid, wrong_node = [], [], []
    group_examples = []
    node_scope_counts = Counter()
    for (key, node), group in node_groups.items():
        node_scope_counts[scopes.get(key, 'no_parent')] += len(group)
        multiplicity[len(group)] += 1
        header = specs['node']['header']
        exact_extra += len(group) - len({tuple(r[f] for f in header) for r in group})
        varying = tuple(f for f in header if len({r[f] for r in group}) > 1)
        if varying:
            varying_fields[varying] += 1
        coordinates = set()
        for r in group:
            try:
                pair = (Decimal(r['LATITUDE']), Decimal(r['LONGITUDE']))
                if not all(v.is_finite() for v in pair) or not (-90 <= pair[0] <= 90 and -180 <= pair[1] <= 180):
                    raise ValueError('Invalid coordinate')
                coordinates.add(pair)
            except (InvalidOperation, ValueError):
                invalid.append(r)
        if len(coordinates) > 1:
            coordinate_conflicts.append({'accident_no': key, 'node_id': node, 'rows': group})
        if key in crashes and crashes[key]['NODE_ID'] != node:
            wrong_node.append({'accident_no': key, 'expected': crashes[key]['NODE_ID'], 'observed': node,
                               'row_locators': [r['row_locator'] for r in group]})
        if len(group_examples) < 5 and (varying or len(group) > 2):
            group_examples.append({'accident_no': key, 'node_id': node, 'varying_fields': varying,
                                   'rows': group})
    missing_nodes = []
    for key, r in crashes.items():
        if (key, r['NODE_ID']) not in node_groups:
            missing_nodes.append({**context(key), 'same_node_other_accidents': sorted(by_node.get(r['NODE_ID'], set()))})

    def scoped_summary(entries):
        return dict(Counter(scopes.get(r['accident_no'], 'no_parent') for r in entries))

    report = {'review_version': 'vic-links-v1', 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Read-only local observations; no source approval or business transformation',
        'inputs': inputs, 'config_sha256': sha256(config_path),
        'code_sha256': {name: sha256(ROOT / 'tools' / name) for name in ('review_vic_links.py', 'profile_vic_inputs.py')},
        'person': {
            'reference_counts': [dict(zip(('road_user_type', 'description', 'scope', 'reference', 'rows'), (*k, n)))
                                 for k, n in sorted(reference_counts.items())],
            'unmatched': unmatched, 'unmatched_scope_counts': scoped_summary(unmatched),
            'unmatched_crash_context': [context(key) for key in sorted({r['accident_no'] for r in unmatched})],
            'blank_nonpedestrians': blank_other, 'blank_nonpedestrian_scope_counts': scoped_summary(blank_other),
            'pedestrians_with_nonblank_vehicle': pedestrian_linked,
            'numeric_person_id_by_road_user_type': dict(all_person_ids_numeric),
            'type16': {'rows': len(type16), 'scope_counts': scoped_summary(type16), 'examples': type16[:5],
                       'linked_vehicle_type_counts': dict(Counter(v['VEHICLE_TYPE'] for r in type16
                            for v in vehicles[r['accident_no']] if v['VEHICLE_ID'] == r['VEHICLE_ID']))}},
        'count_differences': count_differences,
        'vehicle_type21': {'rows': len(type21), 'scope_counts': scoped_summary(type21), 'examples': type21[:5],
                          'linked_person_type_counts': dict(Counter(p['ROAD_USER_TYPE'] for r in type21
                               for p in persons[r['accident_no']] if p['VEHICLE_ID'] == r['VEHICLE_ID']))},
        'node': {'scope_row_counts': dict(node_scope_counts), 'matching_groups': len(node_groups),
                 'rows_per_group_distribution': dict(sorted(multiplicity.items())),
                 'exact_duplicate_extra_rows': exact_extra,
                 'varying_fields': [{'fields': k, 'groups': n} for k, n in varying_fields.items()],
                 'distinct_node_ids': len(by_node), 'node_ids_shared_across_accidents': sum(len(v)>1 for v in by_node.values()),
                 'coordinate_conflicts': coordinate_conflicts, 'invalid_coordinates': invalid,
                 'node_id_differs_from_accident': wrong_node, 'example_groups': group_examples,
                 'missing_matches': missing_nodes, 'missing_scope_counts': scoped_summary(missing_nodes)},
        'inputs_unchanged': all(sha256(paths[name]) == data['file_sha256'] for name, data in inputs.items())}
    if not report['inputs_unchanged']:
        raise ValueError('Inputs changed during the review')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config/native-inputs.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; choose a new filename.')
    try:
        result = review(args.config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'Cannot review VIC links: {exc}\n')
    print(f'Review saved: {args.output}')


if __name__ == '__main__':
    main()
