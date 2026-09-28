"""NSW orphan checks stay exact and avoid a cold-statistics nested anti join."""
import json
import os
from pathlib import Path

import pytest

from arsia_c.projections.nsw import _load_sql, _parameters, _stage_native
from test_c03_nsw_postgres import NSWCase, connection

pytestmark = pytest.mark.skipif('ARSIA_TEST_DSN' not in os.environ,
                              reason='Use the disposable PostgreSQL verifier')


def parameters(case):
    return _parameters(case.context.manifest.as_dict(), case.context.batch_id)


def stage(case):
    with case.connection.cursor() as cursor:
        _stage_native(cursor, parameters(case))


def nodes(plan):
    yield plan
    for child in plan.get('Plans', []):
        yield from nodes(child)


@pytest.mark.parametrize('crashes,units,expected', [
    (['0001', '0002'], [('0001', '01'), ('0002', '01')], (0, 0, 0, 0, 0)),
    ([None, '0001'], [('0001', '01'), ('missing', '01')], (1, 0, 0, 0, 1)),
    ([None, '', '0001', '0001'],
     [(None, '01'), ('', '02'), ('0001', None), ('0001', '01'), ('0001', '01'), ('missing', '02')],
     (2, 1, 3, 1, 1)),
    (['\t\u2003', '0001'], [('\t\u2003', '01'), ('missing', '01')], (1, 0, 1, 0, 1)),
])
def test_orphans_preserve_null_blank_and_duplicate_counts(connection, crashes, units, expected):
    # Synthetic rows test this SQL unit directly, without claiming a full manifest build.
    case = NSWCase(connection)
    for key in crashes:
        case.crash(crash_id=key, year='2019')
    for crash, unit in units:
        case.unit(crash_id=crash, unit_id=unit)
    stage(case)
    actual = connection.execute(_load_sql('c03_nsw_relationship_check.sql'), parameters(case)).fetchone()
    assert actual == expected
    for name, count in (('crash', len(crashes)), ('unit', len(units))):
        assert connection.execute(f'SELECT count(*) FROM pg_temp.c03_nsw_{name}').fetchone() == (count,)


def test_fresh_source_has_scoped_stats_and_bounded_join_plans(connection):
    case = NSWCase(connection)
    for number in range(1000):
        key = f'{number:06}'
        case.crash(crash_id=key)
        case.unit(crash_id=key)
    stage(case)
    plans = {}
    for filename in ('c03_nsw_relationship_check.sql', 'c03_nsw_unit_check.sql'):
        statement = _load_sql(filename)
        plan = connection.execute('EXPLAIN (FORMAT JSON) ' + statement, parameters(case)).fetchone()[0]
        for node in nodes(plan[0]['Plan']):
            if node['Node Type'] == 'Nested Loop':
                # Indexed key lookup is bounded; rescanning the whole parent is not.
                assert any('Index' in child['Node Type'] for child in nodes(node['Plans'][1]))
        plans[filename] = plan
        expected = (0, 0, 0, 0, 0) if 'relationship' in filename else (0,)
        assert connection.execute(statement, parameters(case)).fetchone() == expected
    for table in ('c03_nsw_crash', 'c03_nsw_unit'):
        assert connection.execute('SELECT reltuples FROM pg_class WHERE oid=%s::regclass',
                                  ('pg_temp.' + table,)).fetchone() == (1000.0,)
    if os.environ.get('AC_EVIDENCE_DIR'):
        path = Path(os.environ['AC_EVIDENCE_DIR']) / 'nsw-cold-plan.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'synthetic_rows': 2000,
            'statistics_scope': 'Only loader-owned temporary NSW tables',
            'raw_schema_permissions_and_planner_settings_unchanged': True,
            'plans': plans}, indent=2) + '\n', encoding='utf-8')


def test_staging_repeats_and_obeys_caller_rollback(connection):
    case = NSWCase(connection)
    case.crash()
    case.unit()
    connection.execute('SAVEPOINT before_projection')
    case.run()
    first = connection.execute('SELECT * FROM pg_temp.arsia_i_crash').fetchall()
    case.run()
    assert connection.execute('SELECT * FROM pg_temp.arsia_i_crash').fetchall() == first
    assert connection.execute('SELECT count(*) FROM pg_temp.arsia_i_unit').fetchone() == (1,)
    connection.execute('ROLLBACK TO SAVEPOINT before_projection')
    for table in ('c03_nsw_crash', 'c03_nsw_unit', 'arsia_i_crash', 'arsia_i_unit'):
        assert connection.execute('SELECT to_regclass(%s)', ('pg_temp.' + table,)).fetchone() == (None,)
    assert connection.execute('SELECT count(*) FROM raw.record WHERE source_id=%s',
                              (case.source_id,)).fetchone() == (2,)
