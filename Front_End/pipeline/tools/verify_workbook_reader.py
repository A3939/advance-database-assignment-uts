"""Explicit local XLSX reader audit against an independent OOXML row oracle.

This checks a frozen source's entire selected tables, not semantic admission or
publication. The independently supplied physical headers do not use the reader's
layout heuristic. It emits hashes/aggregates, never person rows. No model or DB.
"""
import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import posixpath
import time
import zipfile

from defusedxml import ElementTree as ET
from arsia_pipeline.intakereaders import detect_tables, iter_table

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'


def _column(reference):
    result = 0
    for char in reference:
        if not char.isalpha():
            break
        result = result * 26 + ord(char.upper()) - ord('A') + 1
    return result - 1


def _xml_rows(archive, member, strings):
    with archive.open(member) as stream:
        for _, elem in ET.iterparse(stream, events=('end',)):
            if elem.tag != NS + 'row':
                continue
            row = []
            for cell in elem.findall(NS + 'c'):
                assert cell.find(NS + 'f') is None, 'Oracle does not approve formula caches'
                index = _column(cell.attrib['r'])
                row.extend([None] * (index + 1 - len(row)))
                kind = cell.get('t', 'n')
                value = cell.findtext(NS + 'v')
                if kind == 'inlineStr':
                    value = ''.join(t.text or '' for t in cell.iter(NS + 't'))
                elif kind == 's':
                    value = strings[int(value)]
                elif value is not None:
                    if kind == 'b':
                        value = 'true' if value == '1' else 'false'
                    else:
                        assert kind == 'n', f'Unsupported oracle cell representation: {kind}'
                        number = Decimal(value)
                        value = str(int(number)) if number == int(number) else str(float(number))
                row[index] = value
            while row and row[-1] is None:
                row.pop()
            yield int(elem.attrib['r']), row
            elem.clear()


def _oracle(archive, sheet, member, strings, header_row):
    header, previous = None, header_row
    for number, values in _xml_rows(archive, member, strings):
        if number < header_row:
            continue
        if number == header_row:
            header = values
            assert len(header) == len(set(header)) and all(isinstance(v, str) and v for v in header)
            continue
        if not values:
            continue # Delay blanks to distinguish internal blanks from an empty tail.
        assert header is not None and len(values) <= len(header)
        for blank in range(previous + 1, number):
            yield json.dumps([sheet, blank], separators=(',', ':')), dict.fromkeys(header)
        values.extend([None] * (len(header) - len(values)))
        yield json.dumps([sheet, number], separators=(',', ':')), dict(zip(header, values, strict=True))
        previous = number


def _digest(rows):
    sha = hashlib.sha256()
    count = 0
    years = Counter()
    sums = Counter()
    crash_ids = set()
    for locator, row in rows:
        count += 1
        sha.update((json.dumps([locator, row], sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
        if row.get('Year'):
            years[row['Year']] += 1
        if row.get('Crash ID'):
            crash_ids.add(row['Crash ID'])
        for field in ('Number fatalities', 'Number of fatal crashes'):
            if row.get(field) is not None:
                sums[field] += int(row[field])
    return {'row_count': count, 'rows_sha256': sha.hexdigest(), 'year_row_counts': dict(sorted(years.items())),
            'declared_count_sums': dict(sums), 'distinct_crash_ids': len(crash_ids) if crash_ids else None}


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    began = time.monotonic()
    sha = hashlib.sha256(args.workbook.read_bytes()).hexdigest()
    assert sha == args.sha256, 'Frozen official source bytes changed'
    file = {'id': 'official-workbook', 'name': args.workbook.name, 'path': str(args.workbook),
            'sha256': sha, 'size': args.workbook.stat().st_size}
    selected = {s.rsplit('=', 1)[0]: int(s.rsplit('=', 1)[1]) for s in args.header}
    tables = detect_tables(file)
    report = {'input_sha256': sha, 'parser_plans': tables, 'tables': {}, 'data_processing_model_calls': 0,
              'raw_person_records_emitted': 0, 'admission_executed': False,
              'limitation': 'Independent XML decoding covers this frozen string/numeric workbook; not arbitrary Excel date styles, semantic QA, an adapter or publication.'}
    with zipfile.ZipFile(args.workbook) as archive:
        root = ET.fromstring(archive.read('xl/sharedStrings.xml')) if 'xl/sharedStrings.xml' in archive.namelist() else []
        strings = [''.join(t.text or '' for t in item.iter(NS + 't')) for item in root]
        links = {e.attrib['Id']: posixpath.normpath(posixpath.join('xl', e.attrib['Target'])).lstrip('/')
                 for e in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets = {s.attrib['name']: links[s.attrib[REL + 'id']]
                  for s in ET.fromstring(archive.read('xl/workbook.xml')).find(NS + 'sheets')}
        assert set(sheets) == set(selected), 'Every physical worksheet requires independent classification'
        for table in tables:
            name = table['sheet']
            assert table['header_row'] == selected[name]
            started = time.monotonic()
            expected = _digest(_oracle(archive, name, sheets[name], strings, selected[name]))
            oracle_seconds = time.monotonic() - started
            started = time.monotonic()
            actual = _digest(iter_table(file, table))
            reader_seconds = time.monotonic() - started
            report['tables'][name] = {'expected': expected, 'actual': actual, 'equal': actual == expected,
                                     'oracle_seconds': oracle_seconds, 'reader_seconds': reader_seconds}
            assert actual == expected, 'Full native values/physical locators differ from the independent oracle'
    if args.executor_image:
        from arsia_pipeline import isolated_executor
        isolated_executor.IMAGE = args.executor_image
        code = '''def adapt(ctx):
    import hashlib, json
    report = {}
    for resource in ctx.contract['resources']:
        sha = hashlib.sha256()
        count = 0
        for locator, row in ctx.iter_rows(resource['role']):
            count += 1
            sha.update((json.dumps([locator, row], sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\\n').encode())
        report[resource['table']['sheet']] = {'row_count': count, 'rows_sha256': sha.hexdigest()}
    (ctx.work_dir / 'parser-audit.json').write_text(json.dumps(report))
'''
        # Deliberately a parsing diagnostic, not a valid semantic source contract.
        # No canonical rows, registry admission, database writes or publication.
        contract = {'resources': [{'role': f'table{i}', 'file_id': file['id'], 'table': table}
                                  for i, table in enumerate(tables)]}
        execution = isolated_executor.run_python(code, [file], args.output / 'executor', mode='full',
                                                source_contract=contract, limits={'seconds': 120, 'memory_mb': 384, 'cpus': 1})
        assert execution['status'] == 'succeeded', execution.get('error')
        audit_path = Path(execution['output_dir']) / 'work' / 'parser-audit.json'
        audit = json.loads(audit_path.read_text())
        assert set(audit) == set(selected)
        for name, result in audit.items():
            assert result == {key: report['tables'][name]['expected'][key] for key in ('row_count', 'rows_sha256')}
        report['executor'] = {'status': 'passed', 'run_id': execution['run_id'], 'image': execution['image'],
                              'usage': execution['usage'], 'code_sha256': execution['code_sha256'],
                              'audit_sha256': hashlib.sha256(audit_path.read_bytes()).hexdigest(),
                              'tables': audit, 'canonical_rows_emitted': 0}
    report.update(status='passed', wall_seconds=time.monotonic() - began)
    (args.output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'wall_seconds': report['wall_seconds'],
                      'tables': {name: {'rows': r['actual']['row_count'], 'equal': r['equal']}
                                 for name, r in report['tables'].items()}}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workbook', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--header', required=True, action='append', help='Reviewed physical header: SHEET=ROW')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--executor-image', help='Explicit immutable-image diagnostic, no semantic admission')
    run(parser.parse_args())
