"""Read-only frozen VIC relationship audit, not an adapter or admission.

The independent oracle uses stdlib CSV and tuple keys, not the intake reader,
canonical projection or inspector SQLite queries. Only aggregate diagnostics
are saved. The output directory must be new; no services or models are used.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import time

from arsia_pipeline.intake_tools import IntakeTools


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def independent_keys(path, fields):
    counts = Counter()
    rows = all_blank = partial_blank = 0
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        assert set(fields) <= set(reader.fieldnames)
        for row in reader:
            assert None not in row and all(value is not None for value in row.values())
            rows += 1
            key = tuple(row[field] for field in fields)
            absent = sum(not value.strip() for value in key)
            if absent == len(key):
                all_blank += 1
            elif absent:
                partial_blank += 1
            else:
                counts[key] += 1
    return counts, rows, all_blank, partial_blank


def oracle(child_path, child_fields, parent_path, parent_fields):
    parents, parent_rows, parent_blank, parent_partial = independent_keys(parent_path, parent_fields)
    children, child_rows, child_blank, child_partial = independent_keys(child_path, child_fields)
    matches = sum(n for key, n in children.items() if parents[key] == 1)
    ambiguous = sum(n for key, n in children.items() if parents[key] > 1)
    return {
        'parent_rows': parent_rows, 'parent_blank_keys': parent_blank + parent_partial,
        'child_rows': child_rows, 'child_blank_keys': child_blank + child_partial,
        'child_all_blank_keys': child_blank, 'child_partial_blank_keys': child_partial,
        'parent_invalid_keys': 0, 'child_invalid_keys': 0,
        'matched_children': matches,
        'unmatched_children': sum(n for key, n in children.items() if key not in parents),
        'ambiguous_parent_children': ambiguous,
        'projected_inner_join_rows': sum(n * parents[key] for key, n in children.items()),
        'join_extra_rows': sum(n * (parents[key] - 1) for key, n in children.items() if parents[key]),
        'duplicate_parent_key_groups': sum(n > 1 for n in parents.values()),
        'max_children_per_parent': max((children[key] for key in parents), default=0),
        'parents_without_children': sum(key not in children for key in parents),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    files = []
    for role in ('accident', 'node', 'vehicle', 'person'):
        path = (args.raw / ('vic_' + role + '.csv')).resolve()
        files.append({'id': role, 'name': path.name, 'path': str(path),
                      'size': path.stat().st_size, 'sha256': digest(path)})
    by_id = {file['id']: file for file in files}
    tools = IntakeTools(files, args.output / 'inspection')
    pairs = [
        ('accident', ['NODE_ID'], 'node', ['NODE_ID']),
        ('accident', ['ACCIDENT_NO', 'NODE_ID'], 'node', ['ACCIDENT_NO', 'NODE_ID']),
        ('node', ['ACCIDENT_NO'], 'accident', ['ACCIDENT_NO']),
        ('vehicle', ['ACCIDENT_NO'], 'accident', ['ACCIDENT_NO']),
        ('person', ['ACCIDENT_NO'], 'accident', ['ACCIDENT_NO']),
        ('person', ['ACCIDENT_NO', 'VEHICLE_ID'], 'vehicle', ['ACCIDENT_NO', 'VEHICLE_ID']),
    ]
    results = []
    for child, child_fields, parent, parent_fields in pairs:
        tick = time.monotonic()
        result = tools.inspect_relations(child, child_fields, parent, parent_fields, allow_blank=True)
        expected = oracle(Path(by_id[child]['path']), child_fields, Path(by_id[parent]['path']), parent_fields)
        assert result['metrics'] == expected, (child, parent, result['metrics'], expected)
        result.update(independent_oracle_equal=True, wall_seconds=time.monotonic() - tick)
        results.append(result)
        (args.output / ('relation-' + str(len(results)) + '.json')).write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'child': child, 'parent': parent, 'fields': child_fields,
                          'structurally_valid': result['structurally_valid'], 'oracle_equal': True}), flush=True)
    assert all(digest(Path(file['path'])) == file['sha256'] for file in files)
    report = {'status': 'relationship_measurements_verified_not_admission', 'files': files,
              'relations': results, 'wall_seconds': time.monotonic() - started,
              'input_hashes_unchanged': True, 'model_calls': 0, 'database_access': False,
              'scope': 'Existing frozen local VIC CSVs; not the current portal full exports.',
              'limitations': ['Structural matches do not prove field meaning, CRS or lookup authority.',
                             'No filtering, adapter execution, QA admission, publication or native policy changes.']}
    (args.output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
