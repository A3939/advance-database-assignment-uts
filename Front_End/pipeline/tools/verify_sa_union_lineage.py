"""Independent audit of a locally partitioned SA acceptance input and output.

Uses standard-library CSV/ZIP/date parsing, never the SDK, shared readers or
canonical projector. Only test artifacts are written; no databases or models.
An oracle copy keeps every source expectation and only rebinds the validated
packaging hash/geographic file path for the existing read-only DB verifier.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import shutil
import time
import zipfile


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def rows(raw):
    return csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))


def signature(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def audit(lab, original, oracle_path, output):
    started = time.monotonic()
    oracle = json.loads(oracle_path.read_text())
    assert oracle['state'] == 'sa' and oracle['oracle_version'] == 3
    assert digest(original) == oracle['input_upload_sha256']
    derived = lab/'derived-union-test.zip'
    initial = json.loads((lab/'initial.json').read_text())
    acceptance = json.loads((lab/'acceptance.json').read_text())
    assert acceptance['status'] == 'passed' and digest(derived) == acceptance['input_sha256']
    runs = [(p, json.loads(p.read_text())) for p in (lab/'lab/attempts'/initial['id']).rglob('execution.json')]
    full = [(p, e) for p, e in runs if e['mode'] == 'full' and e['status'] == 'succeeded']
    assert len(full) == 1
    candidate = full[0][0].parent/'output/crashes.jsonl'
    expected = {}; locators = {}; partitions = []; before = Counter(); after = Counter()
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(derived) as target:
        source_crash = [n for n in source.namelist() if n.endswith('_Crash.csv')]
        assert len(source_crash) == 1
        source_other = set(source.namelist()) - set(source_crash)
        target_crash = [n for n in target.namelist() if n.endswith('_Crash.csv')]
        assert 2 <= len(target_crash) <= 24
        assert set(target.namelist()) - set(target_crash) == source_other
        assert len(set(target.namelist())) == len(target.namelist())
        for name in source_other:
            assert source.read(name) == target.read(name), 'Non-crash input changed'
        for row in rows(source.read(source_crash[0])):
            key = row['REPORT_ID']
            assert key not in expected
            expected[key] = row
            before[signature(row)] += 1
        for name in sorted(target_crash):
            raw = target.read(name); sha = hashlib.sha256(raw).hexdigest(); count = 0
            for count, row in enumerate(rows(raw), 1):
                key = row['REPORT_ID']
                assert key not in locators, 'Cross-partition business key duplicated'
                assert row == expected[key], 'Original field changed or key invented'
                locators[key] = ['homogeneous-union-v1', sha, 'default', f'csv:{count}']
                after[signature(row)] += 1
            partitions.append({'member': name, 'sha256': sha, 'rows': count})
    assert before == after and expected.keys() == locators.keys()
    seen = set(); physical = set(); canonical_ids = set()
    categories = {'1: PDO': 'property_damage_only', '2: MI': 'minor_injury', '3: SI': 'serious_injury', '4: Fatal': 'fatal'}
    with candidate.open() as stream:
        for line in stream:
            actual = json.loads(line); key, = json.loads(actual['record_id'])
            assert key not in seen and actual['canonical_id'] not in canonical_ids
            seen.add(key); canonical_ids.add(actual['canonical_id'])
            raw = expected[key]
            assert actual['extensions'] == raw and actual['raw_key'] == [key]
            assert json.loads(actual['row_locator']) == locators[key]
            assert actual['row_locator'] not in physical
            physical.add(actual['row_locator'])
            date = datetime.strptime(raw['Crash Date Time'], '%d/%m/%Y %H:%M:%S')
            assert actual['occurrence_date'] == date.date().isoformat()
            assert actual['year'] == date.year and actual['month'] == date.month
            assert actual['raw_severity'] == raw['CSEF Severity']
            assert actual['severity'] == categories[raw['CSEF Severity']]
            assert actual['is_fatal_crash'] == (raw['CSEF Severity'] == '4: Fatal')
            for field, source_field in [('fatalities','Total Fats'), ('casualties','Total Cas'),
                                        ('declared_casualties','Total Cas'), ('declared_units','Total Units')]:
                assert actual[field] == int(raw[source_field])
    assert seen == expected.keys()
    # Reuse frozen independent expectations, never calculate expected metrics
    # from the implementation's output. Geography oracle stays byte-identical.
    geo = Path(oracle['geography']['records_path'])
    assert digest(geo) == oracle['geography']['records_sha256']
    target_geo = output/geo.name
    shutil.copyfile(geo, target_geo)
    adapted = json.loads(json.dumps(oracle))
    adapted['input_upload_sha256'] = digest(derived)
    adapted['geography']['records_path'] = str(target_geo.resolve())
    adapted['test_packaging_derivation'] = {
        'scope': 'Local test packaging only; all source CSV fields and non-crash members verified unchanged. Not an official publisher ZIP.',
        'original_oracle_sha256': digest(oracle_path), 'original_upload_sha256': digest(original),
        'validation_record': 'verification.json'}
    (output/'independent-oracle-v3-test-packaging.json').write_text(json.dumps(adapted, indent=2))
    report = {'status': 'passed', 'rows': len(seen), 'partitions': partitions,
        'all_original_fields_and_multiplicities_equal': True, 'all_physical_locators_equal': True,
        'original_business_keys_preserved': True, 'dates_categories_counts_per_key_equal': True,
        'non_crash_members_byte_identical': True, 'candidate_sha256': digest(candidate),
        'original_oracle_sha256': digest(oracle_path), 'original_upload_sha256': digest(original),
        'derived_upload_sha256': digest(derived), 'seconds': time.monotonic()-started,
        'real_model_calls': 0, 'database_access': False,
        'limits': 'Canonical file audit only. Published DB/query and transformed coordinates require separate read-only oracle acceptance.'}
    (output/'verification.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in ('status','rows','seconds')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('lab', 'original', 'oracle', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new evidence directory')
    args.output.mkdir(parents=True, mode=0o700)
    try:
        audit(args.lab.resolve(), args.original.resolve(), args.oracle.resolve(), args.output.resolve())
    except Exception as exc:
        (args.output/'failure.json').write_text(json.dumps({'type': type(exc).__name__, 'message': str(exc)}, indent=2))
        raise
