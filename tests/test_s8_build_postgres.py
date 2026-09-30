"""AT15 through the real installed build, QA gate and reader queries."""
from dataclasses import replace
from decimal import Decimal
import csv
import hashlib
import json
import os
from pathlib import Path

import pytest

if 'AC_TEST_RUN' not in os.environ:
    pytest.skip('Use tools/verify_s8_postgres.py', allow_module_level=True)

import psycopg
from arsia_d05 import TrendRequest, query_trend
from arsia_d06 import SeverityRequest, query_severity
from arsia_d07 import MapRequest, query_map
from arsia_d08 import UnitRequest, query_units
from arsia_ingest.build import s0_request, s8_request
from arsia_ingest.manifest import FrozenManifest, s0_definitions
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import ModuleConnection, run_build
from test_full_build_postgres import ROOT, connect, deployed, private_database, current, run

BATCH_TABLES = ('rv.sat_crash', 'rv.sat_unit', 'rv.link_crash_unit', 'canonical.crash',
                'canonical.unit', 'dw.dim_source', 'dw.dim_severity', 'dw.fact_crash', 'qa.check_result')


def rows(connection, batch):
    return {table: connection.execute(
        f'SELECT to_jsonb(t) FROM {table} t WHERE batch_id=%s ORDER BY to_jsonb(t)::text',
        (batch,)).fetchall() for table in BATCH_TABLES}


@pytest.fixture
def requests(request, tmp_path):
    root = Path(os.environ.get('AC_EVIDENCE_DIR', tmp_path)) / 's8' / request.node.name
    def factory(kind='s8', *, changes=None, unconfirmed_crs=False, coverage_patch=None):
        config = ROOT / 'tests/fixtures' / kind / 'config.json'
        if changes or unconfirmed_crs or coverage_patch is not None:
            import importlib.util
            spec = importlib.util.spec_from_file_location('s8_generator', ROOT / 'tools/create_s0_inputs.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            config = module.create_s0(root / 'changed-inputs', 's8', reuse_s0=ROOT / 'tests/fixtures/s0')
            native = config.parent / 'syn_sa_crash.csv'
            with native.open(newline='', encoding='utf-8-sig') as handle:
                reader = csv.DictReader(handle)
                headers, data = reader.fieldnames, list(reader)
            data[0].update(changes or {})
            with native.open('w', newline='', encoding='utf-8-sig') as handle:
                writer = csv.DictWriter(handle, fieldnames=headers)
                writer.writeheader()
                writer.writerows(data)
            digest = hashlib.sha256(native.read_bytes()).hexdigest()
            for path in (config, config.parent / 'contract.json'):
                value = json.loads(path.read_text(encoding='utf-8'))
                resource = next(r for r in value['resources'] if r['resource_id'] == 'syn_sa_crash')
                resource.get('native', resource)['expected_sha256'] = digest
                if coverage_patch is not None and 'coverage' in resource:
                    resource['coverage'].update(coverage_patch)
                if unconfirmed_crs and 'mapping' in resource:
                    resource['mapping']['location']['crs'] = None
                    resource['mapping']['location']['basis'] = 'Synthetic test: CRS declaration is unconfirmed.'
                path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
        prepared = prepare(config, root / 'intake')
        assert prepared['status'] == 'prepared'
        assert prepared['raw_count'] == (19 if kind == 's0' else 20)
        recipe = s0_request if kind == 's0' else s8_request
        result = recipe(connect=connect, project_root=ROOT, prepared_run=prepared['run_dir'],
                        evidence_root=root / 'builds', contract_path=config.parent / 'contract.json')
        assert type(result['manifest']) is FrozenManifest
        return result
    return factory


def test_at15_s0_to_s8_exact_results_history_and_no_change(requests, deployed):
    baseline = run(requests('s0'))
    old = baseline['batch_id']
    with connect() as connection:
        before = rows(connection, old)
    expanded_request = requests()
    expanded = run(expanded_request)
    batch = expanded['batch_id']
    assert expanded['previous_batch_id'] == old
    assert expanded['input_fingerprint'] != baseline['input_fingerprint']
    with connect() as connection:
        assert current(connection) == batch
        assert rows(connection, old) == before
        assert connection.execute('SELECT count(*) FROM raw.record').fetchone() == (20,)
        expected = {'rv.sat_crash': 7, 'rv.sat_unit': 6, 'rv.link_crash_unit': 6,
                    'canonical.crash': 7, 'canonical.unit': 6, 'dw.dim_source': 4,
                    'dw.dim_severity': 16, 'dw.fact_crash': 7, 'qa.check_result': 77}
        after = rows(connection, batch)
        assert {t: len(data) for t, data in after.items()} == expected
        # Shared native files reuse the same Raw IDs. Only the batch identity changes.
        for table in BATCH_TABLES[:-1]:
            strip = lambda data: sorted((json.dumps({k: v for k, v in r[0].items() if k != 'batch_id'},
                                            sort_keys=True, default=str) for r in data
                                         if r[0]['source_id'] != 'syn_sa'))
            assert strip(after[table]) == strip(before[table]), table
        definitions = s0_definitions(ROOT / 'tests/fixtures/s8/contract.json')
        for table, entries, fields in (
            ('dw.dim_source', definitions['sources'], ('source_id', 'source_name', 'jurisdiction_code', 'release_label', 'release_scope')),
            ('dw.dim_severity', definitions['severity'], ('source_id', 'severity_code', 'severity_label', 'definition_version', 'definition_text')),
        ):
            actual = connection.execute(f"SELECT {','.join(fields)} FROM {table} WHERE batch_id=%s", (batch,)).fetchall()
            assert sorted(actual) == sorted(tuple(row[key] for key in fields) for row in entries)
        assert connection.execute('SELECT * FROM dw.dim_month ORDER BY month_id').fetchall() == [
            (year * 100 + month, year, month) for year in range(2020, 2025) for month in range(1, 13)]
        assert set(connection.execute("SELECT severity_code FROM dw.dim_severity WHERE batch_id=%s AND source_id='syn_sa'", (batch,)).fetchall()) == {('F',), ('I',), ('N',), ('__MISSING__',)}
        actual = connection.execute('''SELECT count(*),count(*) FILTER (WHERE fatal_crash_eligible AND is_fatal_crash),
            sum(fatality_count) FILTER (WHERE fatality_eligible),sum(casualty_count) FILTER (WHERE casualty_eligible),
            count(*) FILTER (WHERE map_eligible) FROM dw.fact_crash WHERE batch_id=%s''', (batch,)).fetchone()
        assert actual == (7, 3, 4, 8, 5)
        sa = connection.execute('''SELECT occurrence_year,occurrence_month,occurrence_date,date_precision,
            severity_raw,severity_code,is_fatal_crash,fatality_count,casualty_count,
            fatal_crash_eligible,fatality_eligible,casualty_eligible,latitude,longitude,location_crs,
            map_eligible,raw_record_id=location_record_id FROM canonical.crash
            WHERE batch_id=%s AND source_id='syn_sa' ''', (batch,)).fetchone()
        assert sa == (2020, 1, None, 'month', 'F', 'F', True, 1, 1, True, True, True,
                      Decimal('-34.9200000'), Decimal('138.6000000'), 'EPSG:4326', True, True)
        assert connection.execute("SELECT payload->>'CRASH_ID' FROM raw.record WHERE source_id='syn_sa'").fetchall() == [('0001',)]
        counts = dict(connection.execute("SELECT rule_id,count(*) FROM qa.check_result WHERE batch_id=%s AND object_key<>'batch' GROUP BY rule_id", (batch,)).fetchall())
        assert counts == dict(zip(('QA01_INPUT', 'QA02_RAW', 'QA03_PROJECTED', 'QA04_AUXILIARY',
                                  'QA05_SEMANTICS', 'QA06_RECONCILIATION', 'QA07_LOCATION'), (8, 8, 6, 4, 4, 20, 20)))
        assert connection.execute("SELECT count(*) FROM qa.check_result WHERE batch_id=%s AND result='block'", (batch,)).fetchone() == (0,)
    with psycopg.connect(deployed) as reader:
        scoped = ModuleConnection(reader)
        old_trend = query_trend(scoped, TrendRequest('synthetic', old))
        assert len(old_trend) == 15 and sum(r['crash_count'] for r in old_trend) == 6
        yearly = query_trend(scoped, TrendRequest('synthetic', batch))
        monthly = query_trend(scoped, TrendRequest('synthetic', batch, grain='month'))
        assert len(yearly) == 20 and len(monthly) == 240
        assert sum(r['crash_count'] for r in yearly) == 7
        assert sum(r['fatal_crash_count'] or 0 for r in yearly) == 3
        assert sum(r['fatality_count'] or 0 for r in yearly) == 4
        assert sum(r['casualty_count'] or 0 for r in yearly) == 8
        sa_monthly = query_trend(scoped, TrendRequest('synthetic', batch, grain='month', source_ids=('syn_sa',)))
        assert len(sa_monthly) == 60 and sum(r['crash_count'] for r in sa_monthly) == 1
        assert all(r['coverage_status'] == 'covered' for r in sa_monthly)
        empty = next(r for r in sa_monthly if r['period_year'] == 2020 and r['period_month'] == 2)
        assert empty['crash_count'] == 0 and empty['fatality_count'] is None and empty['casualty_count'] is None
        severity = query_severity(scoped, SeverityRequest('synthetic', batch))
        assert len(severity) == 7
        assert [(r['severity_code'], r['crash_count']) for r in severity if r['source_id'] == 'syn_sa'] == [('F', 1)]
        mapped = query_map(scoped, MapRequest('synthetic', batch))
        assert len(mapped.points) == 5
        assert (mapped.coverage['point_count'], mapped.coverage['crash_count'], mapped.coverage['coverage_percentage']) == (5, 7, Decimal('71.43'))
        sa_map = query_map(scoped, MapRequest('synthetic', batch, source_ids=('syn_sa',)))
        assert len(sa_map.points) == 1 and sa_map.coverage['coverage_percentage'] == 100
        assert query_units(scoped, UnitRequest('synthetic', batch, source_ids=('syn_sa',))) == ()
        assert sum(r['unit_count'] for r in query_units(scoped, UnitRequest('synthetic', batch))) == 6
    repeated = run_build(**requests()).as_dict()
    assert repeated['result'] == 'no_change' and repeated['batch_id'] == batch
    with connect() as connection:
        assert rows(connection, old) == before and rows(connection, batch) == after
        assert connection.execute('SELECT count(*) FROM raw.record').fetchone() == (20,)
    evidence = Path(expanded['evidence_ref']) / 'at15-assertions.json'
    evidence.write_text(json.dumps({'baseline_batch_id': old, 'expanded_batch_id': batch,
        'actual': dict(raw=20, crashes=7, units=6, fatal_crashes=3, fatalities=4, casualties=8,
                       map_points=5, map_denominator=7, qa_rows=77),
        'old_sources_unchanged': True, 'old_batch_unchanged': True, 'repeat_result': repeated['result'],
        'scope': 'Private synthetic acceptance; independent E sign-off remains separate'}, indent=2) + '\n', encoding='utf-8')


def assert_failed_preserves_baseline(requests, candidate, stage):
    baseline = run(requests('s0'))
    with connect() as connection:
        before = rows(connection, baseline['batch_id'])
    failed = run_build(**candidate).as_dict()
    assert failed['result'] == 'failed' and failed['stage'] == stage, failed
    with connect() as connection:
        assert current(connection) == baseline['batch_id']
        assert rows(connection, baseline['batch_id']) == before
        assert all(not value for value in rows(connection, failed['batch_id']).values())
        assert connection.execute("SELECT count(*) FROM rv.hub_crash WHERE source_id='syn_sa'").fetchone() == (0,)
        assert connection.execute('SELECT status FROM meta.batch WHERE batch_id=%s', (failed['batch_id'],)).fetchone() == ('failed',)
    return failed


def test_at15_bad_sa_key_fails_and_keeps_b0(requests):
    failed = assert_failed_preserves_baseline(requests, requests('s8-bad-key'), 'project')
    assert (Path(failed['evidence_ref']) / 'error.json').is_file()


@pytest.mark.parametrize('stage', ['vault', 'dw', 'publish'])
def test_s8_caller_failure_rolls_back_candidate(requests, stage):
    candidate = requests()
    original = getattr(candidate['modules'], stage)
    def fail(connection, context):
        original.callback(connection, context)
        raise RuntimeError('Injected failure after the real S8 stage')
    candidate['modules'] = replace(candidate['modules'], **{stage: replace(original, callback=fail)})
    assert_failed_preserves_baseline(requests, candidate, stage)


@pytest.mark.parametrize('change', [
    {'MONTH': '13'}, {'YEAR': 'bad'}, {'FATALITIES': '-1'}, {'CASUALTIES': '1.5'}, {'SEVERITY': 'UNKNOWN'},
])
def test_invalid_sa_values_block_without_replacing_b0(requests, change):
    assert_failed_preserves_baseline(requests, requests(changes=change), 'project')


@pytest.mark.parametrize('assignment', [
    'fatality_count=2', 'casualty_count=2', 'occurrence_month=2', 'latitude=-35',
])
def test_sa_independent_qa_rejects_consistent_but_wrong_projection(requests, assignment):
    candidate = requests()
    original = candidate['modules'].project
    def corrupt(connection, context):
        original.callback(connection, context)
        with connection.cursor() as cursor:
            cursor.execute(f"UPDATE pg_temp.arsia_i_crash SET {assignment} WHERE source_id='syn_sa'")
            assert cursor.rowcount == 1
    candidate['modules'] = replace(candidate['modules'], project=replace(original, callback=corrupt))
    failed = assert_failed_preserves_baseline(requests, candidate, 'qa_c')
    assert failed['error_code'] == 'C10_BLOCK', failed


@pytest.mark.parametrize('rule', ['QA05_SEMANTICS', 'QA06_RECONCILIATION', 'QA07_LOCATION'])
def test_real_e_gate_requires_new_sa_objects(requests, rule):
    candidate = requests()
    original = candidate['modules'].publish
    connection = psycopg.connect(os.environ['ARSIA_TEST_ADMIN_DSN'])
    connection.execute('SET ROLE arsia_loader')
    candidate['connect'] = lambda: connection
    def omit(shared, context):
        connection.execute('RESET ROLE')
        deleted = connection.execute("DELETE FROM qa.check_result WHERE batch_id=%s AND rule_id=%s AND object_key LIKE '%%syn_sa%%' RETURNING object_key", (context.batch_id, rule)).fetchall()
        assert deleted
        connection.execute('SET ROLE arsia_loader')
        assert connection.execute('SELECT current_user').fetchone() == ('arsia_loader',)
        return original.callback(shared, context)
    candidate['modules'] = replace(candidate['modules'], publish=replace(original, callback=omit))
    failed = assert_failed_preserves_baseline(requests, candidate, 'publish')
    assert failed['error_code'] == 'PUBLICATION_QA_MISSING', failed


@pytest.mark.parametrize('changes,crs', [
    ({'SEVERITY': ''}, False), ({'FATALITIES': ''}, False), ({'CASUALTIES': ''}, False),
    ({'LATITUDE': ''}, False), ({'LONGITUDE': '180.00000001'}, False), ({}, True),
])
def test_s8_unknown_values_and_limited_location_pass_real_qa(requests, changes, crs):
    result = run(requests(changes=changes, unconfirmed_crs=crs))
    with connect() as connection:
        row = connection.execute("SELECT to_jsonb(t) FROM canonical.crash t WHERE batch_id=%s AND source_id='syn_sa'", (result['batch_id'],)).fetchone()[0]
        for field, column, eligible in (('SEVERITY', 'is_fatal_crash', 'fatal_crash_eligible'),
                                        ('FATALITIES', 'fatality_count', 'fatality_eligible'),
                                        ('CASUALTIES', 'casualty_count', 'casualty_eligible')):
            if field in changes:
                assert row[column] is None and row[eligible] is False
        if crs or {'LATITUDE', 'LONGITUDE'} & changes.keys():
            assert row['map_eligible'] is False
            assert all(row[key] is None for key in ('latitude', 'longitude', 'location_crs', 'location_record_id'))
        assert connection.execute("SELECT count(*) FROM qa.check_result WHERE batch_id=%s", (result['batch_id'],)).fetchone() == (77,)
        assert current(connection) == result['batch_id']


@pytest.mark.parametrize('coverage_patch', [
    {'year_from': 2021}, {'months': [1]}, {'months': 'bad'}, {'year_from': 'bad'},
])
def test_changed_s8_coverage_cannot_publish_or_replace_b0(requests, coverage_patch):
    candidate = requests(coverage_patch=coverage_patch)
    manifest = candidate['manifest'].as_dict()
    coverage = next(c for c in manifest['rules']['contracts'] if c['id'] == 'syn_sa_crash')['content']['identity']['coverage']
    assert all(coverage[key] == value for key, value in coverage_patch.items())
    assert_failed_preserves_baseline(requests, candidate, 'project')
