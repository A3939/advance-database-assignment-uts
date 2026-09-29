"""Read-only frontend extension: source LGA labels → pinned ABS 2024 areas.
No coordinate use, pipeline writes, fuzzy geocoding, or accident-level export.
"""
import calendar
import collections
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# The native source files remain in the original database project, read-only.
# Override this optional rebuild input when the frontend is cloned elsewhere.
RAW = Path(os.environ.get('ARSIA_RAW_DATA_DIR', ROOT.parent / 'Workspace_Github' / 'raw_datasource')).expanduser().resolve()
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
PROV = json.loads((ROOT / 'data/official/provenance.json').read_text())
REPORTS = json.loads((ROOT / 'data/official/reader-results.json').read_text())
GEO = json.loads((ROOT / 'public/geo/provenance.json').read_text())
FILES = {'nsw_crash': 'nsw_crash_2020_2024.xlsx', 'vic_accident': 'vic_accident.csv', 'vic_node': 'vic_node.csv', 'qld_crash': 'qld_crash_locations.csv'}
INPUTS = {p['resourceId']: p for p in PROV['inputs']}
ALIASES = {
    'NSW': {'UNINCORPORATED': '19399'},
    'VIC': {'GEELONG': '22750', 'DANDENONG': '22670', 'BENDIGO': '22620', 'SHEPPARTON': '22830', 'MORELAND': '24700'},
    'QLD': {},
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalise(name):
    # Only explicit administrative suffixes; never approximate string matching.
    name = re.sub(r'\s*\((?:NSW|VIC\.?|QLD)\)\s*$', '', name.upper().strip())
    name = re.sub(r'\s+(?:ABORIGINAL SHIRE|REGIONAL|REGION|CITY|SHIRE|TOWN)$', '', name)
    return re.sub(r'[^A-Z0-9]', '', name)


def xlsx_rows(path):
    with zipfile.ZipFile(path) as z:
        strings = [''.join(t.text or '' for t in si.findall('.//m:t', NS)) for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        header = None
        for _, row in ET.iterparse(z.open('xl/worksheets/sheet1.xml'), events=('end',)):
            if row.tag != '{%s}row' % NS['m']:
                continue
            values = {}
            for cell in row:
                v = cell.find('m:v', NS)
                value = v.text if v is not None else ''
                if cell.get('t') == 's':
                    value = strings[int(value)]
                values[re.sub(r'\d', '', cell.get('r'))] = value
            if header is None:
                header = values
            else:
                yield {header[k]: v for k, v in values.items() if k in header}
            row.clear()


def csv_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)


def number(v):
    if v is None or str(v).strip() in ('', 'Unknown', 'NA'):
        return None
    n = int(v)
    assert n >= 0, 'Negative core measure'
    return n


def total(values):
    return None if any(v is None for v in values) else sum(values)


def build():
    for key, filename in FILES.items():
        assert digest(RAW / filename) == INPUTS['official_' + key]['sha256'], 'Raw source hash mismatch: ' + key
    assert digest(ROOT / 'data/official/reader-results.json') == PROV['evidenceHashes']['reader-results.json']
    catalogs = {}
    lookups = {}
    for source in ('NSW', 'VIC', 'QLD'):
        path = ROOT / f'public/geo/{source.lower()}-lga.geojson'
        expected = next(f for f in GEO['files'] if f['state'] == source.lower())
        assert digest(path) == expected['sha256'], 'Boundary hash mismatch'
        features = json.loads(path.read_text())['features']
        catalogs[source] = [{'id': f['properties']['lga_code_2024'], 'name': f['properties']['lga_name_2024']} for f in features]
        lookups[source] = {normalise(r['name']): r['id'] for r in catalogs[source]}
        assert len(lookups[source]) == len(catalogs[source]), 'Ambiguous normalised boundary names'

    def match(source, name):
        key = normalise(name)
        return ALIASES[source].get(key) or lookups[source].get(key)

    # Join on both source-native accident and node identities; collapse agreeing rows.
    nodes = collections.defaultdict(lambda: {'names': set(), 'all': set(), 'rows': 0})
    node_count = 0
    for row in csv_rows(RAW / FILES['vic_node']):
        node_count += 1
        n = nodes[(row['ACCIDENT_NO'], row['NODE_ID'])]
        n['names'].add(row['LGA_NAME'].strip())
        n['all'].update(x.strip() for x in row['LGA NAME ALL'].split(',') if x.strip())
        n['rows'] += 1
    assert node_count == INPUTS['official_vic_node']['rawCount']
    sources = {}
    months = {m: i for i, m in enumerate(calendar.month_name) if i}
    for source in ('NSW', 'VIC', 'QLD'):
        severity_rows = REPORTS[f'official_{source.lower()}:severity']['rows']
        labels = [r['severity_label'] for r in severity_rows]
        # NSW raw uses human labels, VIC numeric codes, QLD case-insensitive labels.
        severity_lookup = {r['severity_label'].lower(): i for i, r in enumerate(severity_rows)}
        if source == 'VIC':
            severity_lookup = {r['severity_code']: i for i, r in enumerate(severity_rows)}
        cells = {}
        localities = collections.Counter()
        reasons = collections.Counter()
        crosswalk = collections.Counter()
        identities = set()
        duplicate_nodes = 0
        raw_count = 0
        filekey = {'NSW': 'nsw_crash', 'VIC': 'vic_accident', 'QLD': 'qld_crash'}[source]
        rows = xlsx_rows(RAW / FILES[filekey]) if source == 'NSW' else csv_rows(RAW / FILES[filekey])
        for row in rows:
            raw_count += 1
            year = row['Year of crash'] if source == 'NSW' else row['ACCIDENT_DATE'][:4] if source == 'VIC' else row['Crash_Year']
            if year not in ('2020', '2021', '2022', '2023', '2024'):
                continue
            identity = row['Crash ID'] if source == 'NSW' else row['ACCIDENT_NO'] if source == 'VIC' else row['Crash_Ref_Number']
            assert identity not in identities, 'Duplicate crash identity'
            identities.add(identity)
            if source == 'NSW':
                period = f"{year}-{months[row['Month of crash']]:02}"
                label = row['LGA'].strip()
                locality = row['Town'].strip()
                sev = row['Degree of crash - detailed'].lower()
                killed = number(row['No. killed'])
                injured = [number(row[k]) for k in ('No. seriously injured', 'No. moderately injured', 'No. minor-other injured')]
                values = [1, int(sev == 'fatal'), killed, total([killed, *injured])]
                region = match(source, label)
                reason = 'unmatched_name'
            elif source == 'QLD':
                period = f"{year}-{months[row['Crash_Month']]:02}"
                label, locality = row['Loc_Local_Government_Area'].strip(), row['Loc_Suburb'].strip()
                sev = row['Crash_Severity'].lower()
                values = [1, int(sev == 'fatal'), number(row['Count_Casualty_Fatality']), number(row['Count_Casualty_Total'])]
                region = match(source, label)
                reason = 'missing_name' if label in ('', 'Unknown') else 'unmatched_name'
            else:
                period, locality, label = row['ACCIDENT_DATE'][:7], '', ''
                sev = row['SEVERITY']
                values = [1, int(sev == '1'), number(row['NO_PERSONS_KILLED']), total([number(row[k]) for k in ('NO_PERSONS_KILLED', 'NO_PERSONS_INJ_2', 'NO_PERSONS_INJ_3')])]
                n = nodes.get((identity, row['NODE_ID']))
                region, reason = None, 'missing_node'
                if n:
                    duplicate_nodes += n['rows'] > 1
                    labels_native = n['names'] | n['all']
                    label = ' / '.join(sorted(labels_native))
                    candidates = {match(source, x) for x in labels_native}
                    if len(candidates) == 1 and None not in candidates:
                        region = next(iter(candidates))
                    elif len(candidates - {None}) > 1:
                        reason = 'ambiguous_lga'
                    else:
                        reason = 'missing_name' if not label else 'unmatched_name'
            assert sev in severity_lookup, f'Unregistered {source} severity: {sev}'
            key = (period, region or '__unmatched__')
            if key not in cells:
                cells[key] = [0, 0, 0, 0, [0] * len(labels)]
            c = cells[key]
            for i, value in enumerate(values):
                c[i] = None if c[i] is None or value is None else c[i] + value
            c[4][severity_lookup[sev]] += 1
            if region:
                crosswalk[(label, region)] += 1
                if locality and locality.lower() not in ('unknown', 'not stated'):
                    localities[(period, region, locality)] += 1
            else:
                reasons[(period, reason, label)] += 1
        assert raw_count == INPUTS['official_' + filekey]['rawCount']
        # Reconcile every month/metric to the independently exported official reports.
        for expected in REPORTS[f'official_{source.lower()}:monthly']['rows']:
            period = f"{expected['period_year']}-{expected['period_month']:02}"
            observations = [v for (p, _), v in cells.items() if p == period]
            for i, field in enumerate(('crash_count', 'fatal_crash_count', 'fatality_count', 'casualty_count')):
                assert total([c[i] for c in observations]) == expected[field], f'{source} {period} {field} reconciliation failed'
        for i, expected in enumerate(severity_rows):
            assert sum(c[4][i] for c in cells.values()) == expected['crash_count'], 'Severity reconciliation failed'
        matched = sum(v[0] for (_, r), v in cells.items() if r != '__unmatched__')
        sources[source] = {
            'regions': catalogs[source], 'severityLabels': labels,
            'rows': [[p, r, *v] for (p, r), v in sorted(cells.items())],
            'localities': [[p, r, n, c] for (p, r, n), c in sorted(localities.items())],
            'unmatched': [[p, r, n, c] for (p, r, n), c in sorted(reasons.items())],
            'crosswalk': [{'native': n, 'regionId': r, 'crashes': c} for (n, r), c in sorted(crosswalk.items())],
            'audit': {'crashes': len(identities), 'matched': matched, 'unmatched': len(identities)-matched, 'duplicateNodeAccidentsCollapsed': duplicate_nodes, 'monthlyMetricsReconciled': 240, 'severityReconciled': True},
        }
    result = {'extensionVersion': 'lga-name-v1', 'batchId': PROV['batchId'], 'datasetVersion': PROV['version'], 'coverage': PROV['coverage'], 'sources': sources}
    out = ROOT / 'data/regions/aggregates.json'
    out.write_text(json.dumps(result, separators=(',', ':'), ensure_ascii=False) + '\n')
    evidence = {
        'extensionVersion': 'lga-name-v1', 'batchId': PROV['batchId'], 'datasetVersion': PROV['version'],
        'aggregateSha256': digest(out), 'boundaryVersion': 'ABS ASGS 2024 LGA',
        'method': 'Exact state-scoped administrative-name normalisation plus explicit aliases; VIC joins ACCIDENT_NO and NODE_ID and requires all LGA names to agree after mapping. No coordinates or fuzzy matching.',
        'limitations': ['LGA is not a city, suburb or accident point.', 'Historical source labels are displayed on 2024 reference boundaries, not spatially reallocated to 2024 geography.', 'Unmatched and ambiguous records remain in source totals and are excluded from region counts.', 'NSW Town and QLD Suburb are source text labels only. VIC has no admitted town field.', 'This frontend-derived extension does not change official map eligibility, QA07 or the frozen pipeline snapshot.'],
        'inputs': [INPUTS['official_' + key] for key in FILES], 'boundaries': GEO['files'],
        'aliases': ALIASES,
        'references': ['https://geo.abs.gov.au/arcgis/rest/services/ASGS2024/LGA/MapServer/1', 'https://www.merri-bek.vic.gov.au/my-council/news-and-publications/news/merri-bek-name-for-council-approved/'],
        'sources': {s: {'audit': d['audit'], 'unmatchedByReason': dict(collections.Counter({r: sum(x[3] for x in d['unmatched'] if x[1] == r) for r in {x[1] for x in d['unmatched']}})), 'crosswalk': d['crosswalk']} for s, d in sources.items()},
    }
    (ROOT / 'data/regions/provenance.json').write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n')
    (ROOT / 'src/services/region-catalog.json').write_text(json.dumps({s: d['regions'] for s, d in sources.items()}, indent=2) + '\n')
    print(json.dumps({s: d['audit'] for s, d in sources.items()}, indent=2))
    print('Aggregate SHA256:', digest(out))

if __name__ == '__main__':
    build()
