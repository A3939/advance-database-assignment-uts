"""Full pinned official snapshots, real publication and restricted reader output."""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time

import pytest

if 'AC_TEST_RUN' not in os.environ or 'ARSIA_OFFICIAL_NATIVE_ROOT' not in os.environ:
    pytest.skip('Use tools/verify_official_build_postgres.py', allow_module_level=True)

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from arsia_d05 import install_sql as trend_sql
from arsia_d06 import install_sql as severity_sql
from arsia_d07 import install_sql as map_sql
from arsia_d08 import install_sql as units_sql
from arsia_ingest.build import fp1_sql, official_request, s0_request
from arsia_ingest.manifest import FrozenManifest, REQUIRED_CHECKS
from arsia_ingest.official import prepare_official_inputs
from arsia_ingest.official_reader import query_official
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import ModuleConnection, run_build


ROOT = Path(__file__).resolve().parents[1]
TABLES = ('meta.source', 'meta.resource', 'meta.batch', 'meta.current_release', 'raw.record',
          'rv.hub_crash', 'rv.hub_unit', 'rv.sat_crash', 'rv.sat_unit', 'rv.link_crash_unit',
          'canonical.crash', 'canonical.unit', 'dw.dim_source', 'dw.dim_month',
          'dw.dim_severity', 'dw.fact_crash', 'qa.check_result')
BATCH_TABLES = ('rv.sat_crash', 'rv.sat_unit', 'rv.link_crash_unit', 'canonical.crash',
                'canonical.unit', 'dw.dim_source', 'dw.dim_severity', 'dw.fact_crash',
                'qa.check_result')
SOURCES = ('official_nsw', 'official_vic', 'official_qld')


def connect():
    return psycopg.connect(os.environ['ARSIA_TEST_DSN'])


def write(root, name, value):
    (root / name).write_text(json.dumps(value, indent=2, default=str) + '\n', encoding='utf-8')


def current(connection, kind):
    row = connection.execute('SELECT batch_id FROM meta.current_release WHERE dataset_kind=%s',
                             (kind,)).fetchone()
    return str(row[0]) if row else None


def counts(connection, batch):
    return {table: connection.execute(f'SELECT count(*) FROM {table} WHERE batch_id=%s',
                                     (batch,)).fetchone()[0] for table in BATCH_TABLES}


def snapshot(connection, batch):
    """Only the small S0 history is copied to Python."""
    return {table: connection.execute(
        f'SELECT to_jsonb(t) FROM {table} t WHERE batch_id=%s ORDER BY to_jsonb(t)::text',
        (batch,)).fetchall() for table in BATCH_TABLES}


def timed_build(request, root, label):
    stages = []
    modules = request['modules']
    for stage in ('project', 'vault', 'canonical', 'dw', 'qa_c', 'qa_d', 'publish'):
        binding = getattr(modules, stage)
        def timed(connection, context, *, stage=stage, callback=binding.callback):
            started = time.perf_counter()
            try:
                return callback(connection, context)
            finally:
                stages.append({'stage': stage, 'elapsed_seconds': round(time.perf_counter() - started, 3)})
                write(root, label + '-timings.json', stages)
        modules = replace(modules, **{stage: replace(binding, callback=timed)})
    started = time.perf_counter()
    result = run_build(**{**request, 'modules': modules}).as_dict()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write(root, label + '-result.json', {
        'result': result, 'elapsed_seconds': round(time.perf_counter() - started, 3),
        'python_peak_rss_bytes': peak if sys.platform == 'darwin' else peak * 1024,
        'rss_scope': 'Peak for this pytest process since start, including earlier test stages',
        'callback_timings': stages,
    })
    return result


@pytest.fixture(scope='module')
def official():
    root = Path(os.environ['AC_EVIDENCE_DIR']) / 'official-build'
    root.mkdir(parents=True)
    reader_options = conninfo_to_dict(os.environ['ARSIA_TEST_DSN'])
    reader_options['user'] = 'arsia_reader'
    with psycopg.connect(os.environ['ARSIA_TEST_ADMIN_DSN']) as owner:
        assert owner.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ['AC_TEST_RUN'],)
        assert all(owner.execute(f'SELECT count(*) FROM {table}').fetchone() == (0,) for table in TABLES)
        owner.execute(fp1_sql())
        owner.execute('SET LOCAL ROLE arsia_migrator')
        for install in (trend_sql, severity_sql, map_sql, units_sql):
            owner.execute(install())
        owner.execute('RESET ROLE')
        owner.execute(sql.SQL('ALTER ROLE arsia_reader PASSWORD {}').format(sql.Literal(reader_options['password'])))
    try:
        started = time.perf_counter()
        existing = os.environ.get('ARSIA_OFFICIAL_PREPARED_RUN')
        if existing:
            prepared = json.loads((Path(existing) / 'run.json').read_text(encoding='utf-8'))
            prepared['run_dir'] = str(Path(existing).resolve())
        else:
            prepared = prepare_official_inputs(os.environ['ARSIA_OFFICIAL_NATIVE_ROOT'],
                os.environ['ARSIA_OFFICIAL_ARCHIVE_ROOT'], ROOT)
        assert prepared['status'] == 'prepared' and prepared['dataset_kind'] == 'official'
        assert len(prepared['files']) == 7 and prepared['raw_count'] == 2118028
        write(root, 'intake.json', {'receipt': prepared, 'reused': bool(existing),
                                  'elapsed_seconds': round(time.perf_counter() - started, 3)})
        request = official_request(connect=connect, project_root=ROOT,
            prepared_run=prepared['run_dir'], evidence_root=root / 'builds')
        assert type(request['manifest']) is FrozenManifest
        value = request['manifest'].as_dict()
        assert value['dataset_kind'] == 'official'
        assert {row['source_id'] for row in value['sources']} == set(SOURCES)
        assert value['analysis'] == {'year_from': 2020, 'year_to': 2024}
        native_root = Path(os.environ['ARSIA_OFFICIAL_NATIVE_ROOT'])
        catalogue = json.loads((ROOT / 'config/native-inputs.json').read_text(encoding='utf-8'))
        native = []
        expected_files = {row['resource_id']: row for row in value['files']}
        for entry in catalogue['resources']:
            path = native_root / Path(entry['path']).name
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            assert digest == expected_files[entry['resource_id']]['file_sha256']
            native.append({'resource_id': entry['resource_id'], 'path': str(path),
                           'sha256': digest, 'bytes': path.stat().st_size})
        write(root, 'native-files.json', native)
        write(root, 'frozen-manifest.json', value)
        s0 = prepare(ROOT / 'tests/fixtures/s0/config.json', root / 'synthetic-intake')
        baseline = timed_build(s0_request(connect=connect, project_root=ROOT,
            prepared_run=s0['run_dir'], evidence_root=root / 'builds'), root, 's0-baseline')
        assert baseline['result'] == 'succeeded', baseline
        with connect() as connection:
            before = snapshot(connection, baseline['batch_id'])
        publisher = request['modules'].publish
        publication_returned = False
        def fail_after_publish(connection, context):
            nonlocal publication_returned
            publisher.callback(connection, context)
            publication_returned = True
            raise RuntimeError('Official test: caller failure after real E06 publication')
        fault = {**request, 'modules': replace(request['modules'],
            publish=replace(publisher, callback=fail_after_publish))}
        failed = timed_build(fault, root, 'official-publication-rollback')
        assert failed['result'] == 'failed' and failed['stage'] == 'publish', failed
        assert failed['error_code'] == 'RUN_ERROR', failed
        assert publication_returned, failed
        assert failed['message'] == 'publish raised RuntimeError', failed
        with connect() as connection:
            assert current(connection, 'official') is None
            assert current(connection, 'synthetic') == baseline['batch_id']
            assert snapshot(connection, baseline['batch_id']) == before
            assert not any(counts(connection, failed['batch_id']).values())
            for table in ('rv.hub_crash', 'rv.hub_unit'):
                assert connection.execute(f"SELECT count(*) FROM {table} WHERE source_id LIKE 'official_%'").fetchone() == (0,)
            assert connection.execute('SELECT status FROM meta.batch WHERE batch_id=%s',
                                      (failed['batch_id'],)).fetchone() == ('failed',)
            assert connection.execute("SELECT count(*) FROM raw.record WHERE source_id LIKE 'official_%'").fetchone() == (2118028,)
        succeeded = timed_build(request, root, 'official-success')
        assert succeeded['result'] == 'succeeded', succeeded
        with connect() as connection:
            assert current(connection, 'official') == succeeded['batch_id']
            assert current(connection, 'synthetic') == baseline['batch_id']
            assert snapshot(connection, baseline['batch_id']) == before
            actual_counts = counts(connection, succeeded['batch_id'])
            database_bytes = connection.execute('SELECT pg_database_size(current_database())').fetchone()[0]
        write(root, 'database.json', {'successful_batch_counts': actual_counts,
            'database_bytes_after_success': database_bytes, 'official_raw_count': 2118028,
            'synthetic_raw_count': 19, 'failed_batch_empty': True, 'synthetic_history_unchanged': True})
        yield {'root': root, 'request': request, 'value': value, 'failed': failed,
               'succeeded': succeeded, 'baseline': baseline, 'baseline_rows': before,
               'reader_dsn': make_conninfo(**reader_options), 'counts': actual_counts}
    finally:
        # Only this verifier's marked container is cleaned; no shared database is accepted.
        with psycopg.connect(os.environ['ARSIA_TEST_ADMIN_DSN']) as owner:
            assert owner.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ['AC_TEST_RUN'],)
            owner.execute('TRUNCATE ' + ','.join(TABLES))


def test_full_files_and_raw_are_exactly_pinned(official):
    expected = {r['resource_id']: (r['file_sha256'], r['parser_version'], r['raw_count'])
                for r in official['value']['files']}
    with connect() as connection:
        assert connection.execute('SELECT current_user,session_user').fetchone() == ('arsia_loader', 'arsia_loader')
        actual = connection.execute("""SELECT resource_id,file_sha256,parser_version,count(*)
            FROM raw.record WHERE source_id LIKE 'official_%' GROUP BY 1,2,3 ORDER BY 1""").fetchall()
    assert {r[0]: r[1:] for r in actual} == expected
    write(official['root'], 'raw-counts.json', {'resources': actual, 'total': sum(r[3] for r in actual)})


def test_publication_requires_all_seven_qa_groups(official):
    batch = official['succeeded']['batch_id']
    with connect() as connection:
        rows = connection.execute('''SELECT rule_id,object_key,result,affected_count,evidence
            FROM qa.check_result WHERE batch_id=%s ORDER BY rule_id,object_key''', (batch,)).fetchall()
        assert connection.execute('SELECT dataset_kind,status FROM meta.batch WHERE batch_id=%s',
                                  (batch,)).fetchone() == ('official', 'succeeded')
    summary = {r[0]: r[2] for r in rows if r[1] == 'batch'}
    assert set(summary) == set(REQUIRED_CHECKS)
    assert all(result == 'pass' for rule, result in summary.items() if rule != 'QA07_LOCATION')
    assert summary['QA07_LOCATION'] == 'limited'
    assert all(row[2] in {'pass', 'limited'} and row[4] for row in rows)
    assert all(any(row[0] == rule and row[1] != 'batch' for row in rows) for rule in REQUIRED_CHECKS)
    write(official['root'], 'qa-results.json', {'summary': summary, 'rows': rows})


def test_dimensions_and_full_crash_coverage(official):
    batch = official['succeeded']['batch_id']
    value = official['value']
    with connect() as connection:
        for table, entries, fields in (
            ('dw.dim_source', value['sources'], ('source_id', 'source_name', 'jurisdiction_code', 'release_label', 'release_scope')),
            ('dw.dim_severity', value['rules']['severity'], ('source_id', 'severity_code', 'severity_label', 'definition_version', 'definition_text')),
        ):
            actual = connection.execute(f"SELECT {','.join(fields)} FROM {table} WHERE batch_id=%s", (batch,)).fetchall()
            assert sorted(actual) == sorted(tuple(row[field] for field in fields) for row in entries)
        assert connection.execute('SELECT * FROM dw.dim_month ORDER BY month_id').fetchall() == [
            (y * 100 + m, y, m) for y in range(2020, 2025) for m in range(1, 13)]
        assert connection.execute("SELECT count(*) FROM dw.dim_severity WHERE batch_id=%s AND severity_code='__MISSING__'", (batch,)).fetchone() == (3,)
        expected = connection.execute('''WITH years AS (
            SELECT source_id, CASE source_id
                WHEN 'official_nsw' THEN (payload->>'Year of crash')::integer
                WHEN 'official_vic' THEN extract(year FROM (payload->>'ACCIDENT_DATE')::date)::integer
                WHEN 'official_qld' THEN (payload->>'Crash_Year')::integer END AS year
            FROM raw.record WHERE resource_id IN ('official_nsw_crash','official_vic_accident','official_qld_crash'))
            SELECT source_id,year,count(*) FROM years WHERE year BETWEEN 2020 AND 2024 GROUP BY 1,2 ORDER BY 1,2''').fetchall()
        for table in ('canonical.crash', 'dw.fact_crash'):
            actual = connection.execute(f'''SELECT source_id,occurrence_year,count(*) FROM {table}
                WHERE batch_id=%s GROUP BY 1,2 ORDER BY 1,2''', (batch,)).fetchall()
            assert actual == expected
        assert sum(r[2] for r in expected if r[0] == 'official_vic') == 72170
    write(official['root'], 'source-year-counts.json', {'raw_expected_and_verified': expected})


def test_metrics_match_independent_native_observations(official):
    expected = json.loads((ROOT / 'config/official-expected-results-v1.json').read_text(encoding='utf-8'))
    batch = official['succeeded']['batch_id']
    actual = {}
    with connect() as connection:
        for source, wanted in expected['sources'].items():
            row = connection.execute('''SELECT count(*),
                count(*) FILTER (WHERE fatal_crash_eligible AND is_fatal_crash),
                sum(fatality_count) FILTER (WHERE fatality_eligible),
                sum(casualty_count) FILTER (WHERE casualty_eligible),
                count(*) FILTER (WHERE map_eligible),count(*) FILTER (WHERE NOT map_eligible)
                FROM dw.fact_crash WHERE batch_id=%s AND source_id=%s''', (batch, source)).fetchone()
            measured = dict(zip(('crash_count', 'fatal_crash_count', 'fatality_count',
                                'casualty_count', 'map_count', 'unmapped_count'), row))
            units = connection.execute('''SELECT count(*),count(*) FILTER (WHERE count_eligible)
                FROM canonical.unit WHERE batch_id=%s AND source_id=%s''', (batch, source)).fetchone()
            measured.update(canonical_unit_count=units[0], report_eligible_unit_count=units[1])
            assert measured == {key: wanted[key] for key in measured}
            if 'severity_counts' in wanted:
                severities = dict(connection.execute('''SELECT severity_code,count(*) FROM dw.fact_crash
                    WHERE batch_id=%s AND source_id=%s GROUP BY 1''', (batch, source)).fetchall())
                assert severities == wanted['severity_counts']
                measured['severity_counts'] = severities
            actual[source] = measured
    write(official['root'], 'source-metrics.json', {
        'actual': actual, 'expectations': expected,
        'scope': 'Separate source results; no pooled interstate KPI or independent E acceptance claimed',
    })


def test_vic_restrictions_are_retained_in_storage(official):
    batch = official['succeeded']['batch_id']
    with connect() as connection:
        assert connection.execute('''SELECT count(*) FROM canonical.crash WHERE batch_id=%s
            AND source_id='official_vic' AND (map_eligible OR latitude IS NOT NULL OR longitude IS NOT NULL
            OR location_crs IS NOT NULL OR location_record_id IS NOT NULL)''', (batch,)).fetchone() == (0,)
        assert connection.execute('''SELECT count(*) FROM canonical.unit WHERE batch_id=%s
            AND source_id='official_vic' AND count_eligible''', (batch,)).fetchone() == (0,)
        assert connection.execute('''SELECT count(*) FROM canonical.unit WHERE batch_id=%s
            AND source_id='official_vic' ''', (batch,)).fetchone()[0] > 0
        assert connection.execute('''SELECT count(*) FROM canonical.unit WHERE batch_id=%s
            AND source_id='official_qld' ''', (batch,)).fetchone() == (0,)


def test_reader_returns_source_scoped_results_and_explicit_limits(official):
    batch = official['succeeded']['batch_id']
    outputs = {}
    with connect() as loader:
        expected = dict(loader.execute('SELECT source_id,count(*) FROM dw.fact_crash WHERE batch_id=%s GROUP BY 1', (batch,)).fetchall())
        expected_units = loader.execute("SELECT count(*) FROM canonical.unit WHERE batch_id=%s AND source_id='official_nsw' AND count_eligible", (batch,)).fetchone()[0]
    with psycopg.connect(official['reader_dsn']) as reader:
        assert reader.execute('SELECT current_user').fetchone() == ('arsia_reader',)
        shared = ModuleConnection(reader)
        for source in SOURCES:
            for report in ('trend', 'severity', 'map', 'units'):
                result = query_official(shared, batch_id=batch, source_id=source, report=report)
                outputs[source + ':' + report] = result
                assert result['source_label'] and result['quality_limits'] and result['coverage_basis']
                if source == 'official_vic':
                    assert 'restricted' in result['source_label']
                unavailable = report == 'map' or (report == 'units' and source != 'official_nsw')
                if unavailable:
                    assert result['status'] == 'unavailable' and result['reason'] and result['rows'] is None
                else:
                    assert result['status'] == 'available'
                    assert all(row['source_id'] == source for row in result['rows'])
                    field = 'unit_count' if report == 'units' else 'crash_count'
                    assert sum(row[field] or 0 for row in result['rows']) == (expected_units if report == 'units' else expected[source])
            monthly = query_official(shared, batch_id=batch, source_id=source, report='trend', grain='month')
            assert monthly['status'] == 'available' and len(monthly['rows']) == 60
            outputs[source + ':monthly'] = monthly
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            reader.execute('SELECT payload FROM raw.record LIMIT 1')
        reader.rollback()
        for other_batch in (official['failed']['batch_id'], official['baseline']['batch_id']):
            for report in ('map', 'units'):
                with pytest.raises(psycopg.errors.InvalidParameterValue):
                    query_official(shared, batch_id=other_batch, source_id='official_vic', report=report)
                reader.rollback()
    write(official['root'], 'reader-results.json', outputs)


def test_same_official_input_is_no_change_without_duplicate_rows(official):
    before = official['counts']
    again = timed_build(official['request'], official['root'], 'official-no-change')
    first = official['succeeded']
    assert again['result'] == 'no_change' and again['batch_id'] == first['batch_id']
    assert again['input_fingerprint'] == first['input_fingerprint']
    with connect() as connection:
        assert counts(connection, first['batch_id']) == before
        assert connection.execute("SELECT count(*) FROM raw.record WHERE source_id LIKE 'official_%'").fetchone() == (2118028,)
        assert connection.execute("SELECT count(*) FROM meta.batch WHERE dataset_kind='official'").fetchone() == (2,)
        assert snapshot(connection, official['baseline']['batch_id']) == official['baseline_rows']


def test_real_publish_caller_failure_is_rolled_back(official):
    failed = official['failed']
    assert failed['stage'] == 'publish' and failed['result'] == 'failed'
    assert (Path(failed['evidence_ref']) / 'error.json').is_file()
    with connect() as connection:
        assert not any(counts(connection, failed['batch_id']).values())
        assert current(connection, 'official') == official['succeeded']['batch_id']
        assert current(connection, 'synthetic') == official['baseline']['batch_id']
