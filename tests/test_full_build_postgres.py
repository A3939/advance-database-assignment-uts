"""Real S0 publication, history, reader queries and recovery in private PG16."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import importlib.util
import os
from pathlib import Path
from threading import Event

import pytest

if 'AC_TEST_RUN' not in os.environ:
    pytest.skip('Use tools/verify_full_build_postgres.py', allow_module_level=True)

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from arsia_d05 import TrendRequest, query_trend, install_sql as trend_sql
from arsia_d06 import SeverityRequest, query_severity, install_sql as severity_sql
from arsia_d07 import MapRequest, query_map, install_sql as map_sql
from arsia_d08 import UnitRequest, query_units, install_sql as units_sql
from arsia_ingest.build import fp1_sql, s0_request
from arsia_ingest.manifest import s0_definitions
from arsia_ingest.pipeline import prepare
from arsia_ingest.recovery import recover_run
from arsia_ingest.runner import ModuleConnection, run_build
from test_ac_integration_postgres import TABLES
from test_e_postgres import CASES, mutate

ROOT = Path(__file__).resolve().parents[1]
ALL_TABLES = (*TABLES, 'dw.fact_crash')


def connect():
    return psycopg.connect(os.environ['ARSIA_TEST_DSN'])


@pytest.fixture(scope='module')
def deployed():
    options = conninfo_to_dict(os.environ['ARSIA_TEST_DSN'])
    options['user'] = 'arsia_reader'
    with psycopg.connect(os.environ['ARSIA_TEST_ADMIN_DSN']) as owner:
        assert owner.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ['AC_TEST_RUN'],)
        owner.execute(fp1_sql())
        owner.execute('SET LOCAL ROLE arsia_migrator')
        for install in (trend_sql, severity_sql, map_sql, units_sql):
            owner.execute(install())
        owner.execute('RESET ROLE')
        owner.execute(sql.SQL('ALTER ROLE arsia_reader PASSWORD {}').format(sql.Literal(options['password'])))
    return make_conninfo(**options)


@pytest.fixture(autouse=True)
def private_database(deployed):
    with connect() as conn:
        assert conn.execute('SELECT current_user,session_user').fetchone() == ('arsia_loader', 'arsia_loader')
        assert conn.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ['AC_TEST_RUN'],)
        assert all(conn.execute(f'SELECT count(*) FROM {t}').fetchone() == (0,) for t in ALL_TABLES)
    yield
    # This verifier owns this marked, disposable database. Never run on shared data.
    with psycopg.connect(os.environ['ARSIA_TEST_ADMIN_DSN']) as owner:
        assert owner.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ['AC_TEST_RUN'],)
        owner.execute('TRUNCATE ' + ','.join(ALL_TABLES))


@pytest.fixture
def request_factory(request, tmp_path):
    root = Path(os.environ.get('AC_EVIDENCE_DIR', tmp_path)) / 'full-build' / request.node.name
    prepared = prepare(ROOT / 'tests/fixtures/s0/config.json', root / 'intake')
    assert prepared['raw_count'] == 19
    def factory(*, variant=None, **kwargs):
        selected = prepared
        if variant is not None:
            spec = importlib.util.spec_from_file_location('s0_generator', ROOT / 'tools/create_s0_inputs.py')
            generator = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(generator)
            config = generator.create_s0(root / variant / 'inputs', variant)
            selected = prepare(config, root / 'intake')
            assert selected['status'] == 'prepared'
            kwargs['contract_path'] = config.parent / 'contract.json'
        return s0_request(connect=connect, project_root=ROOT, prepared_run=selected['run_dir'],
                          evidence_root=root / 'runs', **kwargs)
    return factory


def run(request):
    result = run_build(**request).as_dict()
    assert result['result'] == 'succeeded', result
    return result


def current(conn):
    row = conn.execute("SELECT batch_id FROM meta.current_release WHERE dataset_kind='synthetic'").fetchone()
    return str(row[0]) if row else None


def batch_rows(conn, batch):
    return {table: conn.execute(f'SELECT to_jsonb(t) FROM {table} t WHERE batch_id=%s ORDER BY to_jsonb(t)::text',
                               (batch,)).fetchall() for table in (
        'canonical.crash', 'canonical.unit', 'dw.dim_source', 'dw.dim_severity', 'dw.fact_crash', 'qa.check_result')}


def test_committed_real_build_exact_definitions_and_no_change(request_factory):
    request = request_factory()
    first = run(request)
    batch = first['batch_id']
    with connect() as conn:
        assert current(conn) == batch
        assert conn.execute('SELECT status FROM meta.batch WHERE batch_id=%s', (batch,)).fetchone() == ('succeeded',)
        assert conn.execute('SELECT count(*) FROM raw.record').fetchone() == (19,)
        expected_counts = {'canonical.crash': 6, 'canonical.unit': 6, 'dw.dim_source': 3,
                           'dw.dim_severity': 12, 'dw.fact_crash': 6, 'qa.check_result': 63}
        before = batch_rows(conn, batch)
        assert {table: len(rows) for table, rows in before.items()} == expected_counts
        definitions = s0_definitions(ROOT / 'tests/fixtures/s0/contract.json')
        for table, rows, fields in (
            ('dw.dim_source', definitions['sources'], ('source_id', 'source_name', 'jurisdiction_code', 'release_label', 'release_scope')),
            ('dw.dim_severity', definitions['severity'], ('source_id', 'severity_code', 'severity_label', 'definition_version', 'definition_text')),
        ):
            actual = conn.execute(f"SELECT {','.join(fields)} FROM {table} WHERE batch_id=%s", (batch,)).fetchall()
            assert sorted(actual) == sorted(tuple(row[k] for k in fields) for row in rows)
        assert conn.execute('SELECT * FROM dw.dim_month ORDER BY month_id').fetchall() == [
            (y * 100 + m, y, m) for y in range(2020, 2025) for m in range(1, 13)]
        assert conn.execute("SELECT count(*) FROM dw.dim_severity WHERE severity_code='__MISSING__'").fetchone() == (3,)
        assert conn.execute("SELECT count(*) FROM dw.fact_crash WHERE severity_code='__MISSING__'").fetchone() == (1,)
        assert len(first['qa_summary']) == 7
        assert next(r for r in first['qa_summary'] if r['rule_id'] == 'QA07_LOCATION')['affected_count'] == 2
    second = run_build(**request_factory(prepared_by='Different provenance only')).as_dict()
    assert second['result'] == 'no_change', second
    assert second['batch_id'] == batch and second['input_fingerprint'] == first['input_fingerprint']
    with connect() as conn:
        assert conn.execute('SELECT count(*) FROM meta.batch').fetchone() == (1,)
        assert conn.execute('SELECT count(*) FROM raw.record').fetchone() == (19,)
        assert batch_rows(conn, batch) == before


def test_new_rules_publish_without_changing_pinned_reader_history(request_factory, deployed):
    first = run(request_factory())
    with connect() as conn:
        before = batch_rows(conn, first['batch_id'])
    with psycopg.connect(deployed) as reader:
        read = lambda batch: (
            query_trend(ModuleConnection(reader), TrendRequest('synthetic', batch)),
            query_severity(ModuleConnection(reader), SeverityRequest('synthetic', batch)),
            query_map(ModuleConnection(reader), MapRequest('synthetic', batch)),
            query_units(ModuleConnection(reader), UnitRequest('synthetic', batch)),
        )
        old = read(first['batch_id'])
        assert len(old[0]) == 15 and sum(row['crash_count'] for row in old[0]) == 6
        assert len(old[1]) == 6 and len(old[2].points) == 4
        assert sum(row['unit_count'] for row in old[3]) == 6
        second = run(request_factory(analysis={'year_from': 2021, 'year_to': 2024}))
        assert second['input_fingerprint'] != first['input_fingerprint']
        assert second['previous_batch_id'] == first['batch_id']
        assert read(first['batch_id']) == old
        new = read(second['batch_id'])
        assert sum(row['crash_count'] for row in new[0]) == 2
    with connect() as conn:
        assert current(conn) == second['batch_id']
        assert batch_rows(conn, first['batch_id']) == before
        assert conn.execute('SELECT count(*) FROM raw.record').fetchone() == (19,)
        assert conn.execute('SELECT count(*) FROM dw.dim_source').fetchone() == (6,)
        assert conn.execute('SELECT count(*) FROM dw.dim_severity').fetchone() == (24,)


@pytest.mark.parametrize('stage', ['vault', 'dw', 'publish'])
def test_failure_after_real_callback_rolls_back_candidate_preserves_release(request_factory, stage):
    first = run(request_factory())
    with connect() as conn:
        before = batch_rows(conn, first['batch_id'])
    request = request_factory(analysis={'year_from': 2021, 'year_to': 2024})
    original = getattr(request['modules'], stage)
    def fail(connection, context):
        original.callback(connection, context)
        raise RuntimeError('Injected failure after real callback')
    request['modules'] = replace(request['modules'], **{stage: replace(original, callback=fail)})
    failed = run_build(**request).as_dict()
    assert failed['result'] == 'failed' and failed['stage'] == stage, failed
    with connect() as conn:
        assert current(conn) == first['batch_id']
        assert batch_rows(conn, first['batch_id']) == before
        assert all(not rows for rows in batch_rows(conn, failed['batch_id']).values())
        assert conn.execute('SELECT status,error_details->>\'stage\' FROM meta.batch WHERE batch_id=%s',
                            (failed['batch_id'],)).fetchone() == ('failed', stage)
    assert (Path(failed['evidence_ref']) / 'error.json').is_file()
    recovered = recover_run(connect=connect, run_dir=failed['evidence_ref'],
                            evidence_root=Path(failed['evidence_ref']).parent / 'recovery').as_dict()
    assert recovered['resolution'] == 'failed', recovered


@pytest.mark.parametrize('case', CASES)
def test_real_e_gate_rejects_damaged_producer_results(request_factory, case):
    request = request_factory()
    original = request['modules'].publish
    # Owner access changes test rows only. All real callbacks run as arsia_loader.
    connection = psycopg.connect(os.environ['ARSIA_TEST_ADMIN_DSN'])
    connection.execute('SET ROLE arsia_loader')
    request['connect'] = lambda: connection
    def corrupt(shared, context):
        connection.execute('RESET ROLE')
        mutate(connection, context.batch_id, case)
        connection.execute('SET ROLE arsia_loader')
        assert connection.execute('SELECT current_user').fetchone() == ('arsia_loader',)
        return original.callback(shared, context)
    request['modules'] = replace(request['modules'], publish=replace(original, callback=corrupt))
    result = run_build(**request).as_dict()
    assert result['result'] == 'failed' and result['stage'] == 'publish', result
    assert result['error_code'].startswith('PUBLICATION_'), result
    with connect() as conn:
        assert current(conn) is None
        assert all(not rows for rows in batch_rows(conn, result['batch_id']).values())
        assert conn.execute('SELECT status FROM meta.batch WHERE batch_id=%s', (result['batch_id'],)).fetchone() == ('failed',)


def test_concurrent_real_build_is_busy_then_no_change(request_factory):
    entered, release = Event(), Event()
    request = request_factory()
    original = request['modules'].project
    def pause(shared, context):
        original.callback(shared, context)
        entered.set()
        assert release.wait(30), 'Other session did not finish its lock check'
    request['modules'] = replace(request['modules'], project=replace(original, callback=pause))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_build, **request)
        try:
            assert entered.wait(30)
            second = run_build(**request_factory()).as_dict()
            assert second['result'] == 'busy' and second['batch_id'] is None, second
        finally:
            release.set()
        first = future.result(timeout=30).as_dict()
    assert first['result'] == 'succeeded', first
    third = run_build(**request_factory()).as_dict()
    assert third['result'] == 'no_change' and third['batch_id'] == first['batch_id']


class LostCommitReply:
    """Only lose the acknowledgement; the real server commits normally."""
    def __init__(self):
        self.connection = connect()
        self.commits = 0
    def __getattr__(self, name):
        return getattr(self.connection, name)
    def commit(self):
        self.commits += 1
        self.connection.commit()
        if self.commits == 2:
            raise ConnectionError('Injected loss of publication acknowledgement')


def test_lost_publication_reply_recovers_from_real_committed_state(request_factory):
    request = request_factory()
    request['connect'] = LostCommitReply
    result = run_build(**request).as_dict()
    assert result['result'] == 'unknown_commit', result
    with connect() as conn:
        assert current(conn) == result['batch_id']
        assert len(batch_rows(conn, result['batch_id'])['qa.check_result']) == 63
    recovered = recover_run(connect=connect, run_dir=result['evidence_ref'],
                            evidence_root=Path(result['evidence_ref']).parent / 'recovery').as_dict()
    assert recovered['resolution'] == 'succeeded', recovered
    assert run_build(**request_factory()).as_dict()['result'] == 'no_change'


@pytest.mark.parametrize('variant,expected', [('revised_n1', (6, 4, 8)), ('delete_q2', (5, 3, 7))])
def test_real_snapshot_change_keeps_successful_history(request_factory, variant, expected):
    first = run(request_factory())
    with connect() as conn:
        before = batch_rows(conn, first['batch_id'])
    second = run(request_factory(variant=variant))
    assert second['input_fingerprint'] != first['input_fingerprint']
    with connect() as conn:
        assert current(conn) == second['batch_id']
        assert batch_rows(conn, first['batch_id']) == before
        assert conn.execute('SELECT count(*),sum(fatality_count),sum(casualty_count) FROM dw.fact_crash WHERE batch_id=%s',
                            (second['batch_id'],)).fetchone() == expected


def test_unexplained_row_reduction_blocks_before_registration(request_factory):
    first = run(request_factory())
    rejected = run_build(**request_factory(variant='delete_q2_unexplained')).as_dict()
    assert (rejected['result'], rejected['stage'], rejected['error_code']) == ('failed', 'input', 'QA_BLOCK'), rejected
    assert rejected['batch_id'] is None
    with connect() as conn:
        assert current(conn) == first['batch_id']
        assert conn.execute('SELECT count(*) FROM meta.batch').fetchone() == (1,)


@pytest.mark.parametrize('variant', ['duplicate_crash', 'orphan_unit', 'person_vehicle_99',
                                    'invalid_date', 'negative_count', 'undefined_category'])
def test_invalid_native_values_cannot_publish(request_factory, variant):
    rejected = run_build(**request_factory(variant=variant)).as_dict()
    assert rejected['result'] == 'failed', rejected
    assert rejected['stage'] in ('project', 'canonical', 'qa_c'), rejected
    with connect() as conn:
        assert current(conn) is None
        assert all(not rows for rows in batch_rows(conn, rejected['batch_id']).values())
        assert conn.execute('SELECT status FROM meta.batch WHERE batch_id=%s', (rejected['batch_id'],)).fetchone() == ('failed',)


@pytest.mark.parametrize('variant,limited', [('invalid_coordinate', 3), ('unknown_crs', 4)])
def test_allowed_location_limits_publish_without_dropping_crashes(request_factory, variant, limited):
    result = run(request_factory(variant=variant))
    summary = next(row for row in result['qa_summary'] if row['rule_id'] == 'QA07_LOCATION')
    assert summary['result'] == 'limited' and summary['affected_count'] == limited
    with connect() as conn:
        assert conn.execute('SELECT count(*) FROM dw.fact_crash').fetchone() == (6,)
