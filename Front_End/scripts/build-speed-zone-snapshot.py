"""Read-only native speed-zone extension for the pinned frontend snapshot.

No row export, database changes or alteration of the admitted official reports.
Run from this project; ARSIA_RAW_DATA_DIR overrides the optional rebuild inputs.
"""
import calendar
import collections
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('region_readers', ROOT / 'scripts/build-region-snapshot.py')
readers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readers)
BANDS = [('0-50', '≤50'), ('60', '60'), ('70', '70'), ('80-90', '80–90'), ('100-110', '100–110')]
FILES = {'NSW': ('nsw_crash', 'Speed limit'), 'VIC': ('vic_accident', 'SPEED_ZONE'), 'QLD': ('qld_crash', 'Crash_Speed_Limit')}


def band(source, value):
    # Never split QLD's published intervals, infer special code meanings, or
    # silently round VIC's 075 into 70/80. Nonmatching native tokens are retained.
    value = (value or '').strip()
    if source == 'QLD':
        return {'0 - 50 km/h': '0-50', '60 km/h': '60', '70 km/h': '70',
                '80 - 90 km/h': '80-90', '100 - 110 km/h': '100-110'}.get(value)
    match = re.fullmatch(r'(\d+) km/h' if source == 'NSW' else r'(\d+)', value)
    if not match:
        return None
    speed = int(match[1])
    if speed in (10, 20, 30, 40, 50):
        return '0-50'
    if speed in (60, 70):
        return str(speed)
    if speed in (80, 90):
        return '80-90'
    if speed in (100, 110):
        return '100-110'
    return None


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def build():
    prov, reports = readers.PROV, readers.REPORTS
    assert digest(ROOT / 'data/official/reader-results.json') == prov['evidenceHashes']['reader-results.json']
    sources, inputs = {}, []
    months = {m: i for i, m in enumerate(calendar.month_name) if i}
    for source, (key, field) in FILES.items():
        path = readers.RAW / readers.FILES[key]
        expected = readers.INPUTS['official_' + key]
        assert digest(path) == expected['sha256'], f'{source}: raw hash mismatch'
        inputs.append(expected)
        cells, excluded = collections.defaultdict(lambda: [0, 0, 0]), collections.defaultdict(lambda: [0, 0, 0])
        native = collections.Counter()
        ids, raw_count = set(), 0
        severity_rows = reports[f'official_{source.lower()}:severity']['rows']
        labels = {r['severity_code'] if source == 'VIC' else r['severity_label'].lower() for r in severity_rows}
        rows = readers.xlsx_rows(path) if source == 'NSW' else readers.csv_rows(path)
        for row in rows:
            raw_count += 1
            year = row['Year of crash'] if source == 'NSW' else row['ACCIDENT_DATE'][:4] if source == 'VIC' else row['Crash_Year']
            if year not in ('2020', '2021', '2022', '2023', '2024'):
                continue
            identity = row['Crash ID'] if source == 'NSW' else row['ACCIDENT_NO'] if source == 'VIC' else row['Crash_Ref_Number']
            assert identity and identity not in ids, f'{source}: duplicate or absent crash identity'
            ids.add(identity)
            period = row['ACCIDENT_DATE'][:7] if source == 'VIC' else f"{year}-{months[row['Month of crash'] if source == 'NSW' else row['Crash_Month']]:02}"
            severity = row['Degree of crash - detailed'].lower() if source == 'NSW' else row['SEVERITY'] if source == 'VIC' else row['Crash_Severity'].lower()
            assert severity in labels, f'{source}: unregistered severity'
            known = severity not in ('', '__MISSING__')
            fatal = severity == ('1' if source == 'VIC' else 'fatal')
            value = row[field].strip()
            native[value] += 1
            bucket = band(source, value)
            cell = cells[(period, bucket)] if bucket else excluded[(period, value)]
            cell[0] += 1
            cell[1] += int(fatal)
            cell[2] += int(known)
        assert raw_count == expected['rawCount']
        # Independent admitted monthly counts: include excluded zones in reconciliation.
        for row in reports[f'official_{source.lower()}:monthly']['rows']:
            period = f"{row['period_year']}-{row['period_month']:02}"
            observed = [v for (p, _), v in list(cells.items()) + list(excluded.items()) if p == period]
            for i, metric in enumerate(('crash_count', 'fatal_crash_count', 'fatal_crash_known_count')):
                assert sum(v[i] for v in observed) == row[metric], f'{source} {period}: {metric} mismatch'
        sources[source] = {'field': field,
                           'rows': [[p, b, *v] for (p, b), v in sorted(cells.items())],
                           'excluded': [[p, value, *v] for (p, value), v in sorted(excluded.items())],
                           'nativeValues': dict(sorted(native.items())),
                           'audit': {'rawRows': raw_count, 'selectedCrashes': len(ids), 'excludedCrashes': sum(v[0] for v in excluded.values()), 'monthlyMeasuresReconciled': 180}}
    result = {'extensionVersion': 'speed-zone-v1', 'batchId': prov['batchId'], 'datasetVersion': prov['version'],
              'coverage': prov['coverage'], 'bands': [{'id': k, 'label': v} for k, v in BANDS], 'sources': sources}
    out = ROOT / 'data/speed-zones'
    out.mkdir(exist_ok=True)
    (out / 'aggregates.json').write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n')
    evidence = {'extensionVersion': 'speed-zone-v1', 'batchId': prov['batchId'], 'datasetVersion': prov['version'],
                'aggregateSha256': digest(out / 'aggregates.json'), 'readerSha256': prov['evidenceHashes']['reader-results.json'],
                'inputs': inputs, 'sources': {s: {'field': d['field'], 'nativeValues': d['nativeValues'], 'audit': d['audit']} for s, d in sources.items()},
                'method': 'Count distinct native crash events per calendar month and compatible source speed band. Fatal uses the admitted source-native crash severity. Share = fatal events / recorded events in the same source, months and band; unknown fatal status withholds the share.',
                'limitations': ['QLD publishes 0–50, 80–90 and 100–110 intervals; exact source values are grouped only into these whole intervals. No interval is split.', 'NSW unknown limits and VIC 075/777/888/999 are retained separately and excluded from plotted bands; no special-code meaning or speed is inferred.', 'QLD records casualty crashes; source inclusion and severity definitions differ. Shares are not exposure-adjusted risk or state safety rankings.', 'State-wide, whole-month extension only; LGA speed breakdowns are unsupported.', 'Derived frontend extension, not an amendment to the frozen official pipeline report or its permissions.']}
    (out / 'provenance.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'aggregateSha256': evidence['aggregateSha256'], 'sources': {s: d['audit'] for s, d in sources.items()}}, indent=2))


if __name__ == '__main__':
    build()
