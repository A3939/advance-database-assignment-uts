"""Opt-in archive scans and C06/PostgreSQL checks; inventories remain test-only."""
import importlib
import os
from pathlib import Path

import pytest

from arsia_ingest.qa_input import check_inputs, write_evidence
from arsia_ingest.runner import ModuleConnection
from test_manifest import build
from test_raw_load_postgres import connection
from test_vic_restricted import vic_build


@pytest.mark.skipif(not os.environ.get('ARSIA_VIC_ARCHIVE_ROOT'), reason='Needs existing pinned VIC archives; no downloads or preparation are run')
def test_actual_vic_archives_pass_only_restricted_input_checks(vic_build, tmp_path):
    frozen = vic_build[0]
    report = check_inputs(frozen.as_dict(), os.environ['ARSIA_VIC_ARCHIVE_ROOT'],
                          evidence_dir=tmp_path / 'input', producer_version='b11-vic-r1',
                          supported_mappings=frozen.as_dict()['rules']['mappings'])
    write_evidence(tmp_path / 'qa01.json', report.as_dict())
    (tmp_path / 'transport-test-manifest.json').write_text(frozen._json)
    assert not report.blocked
    assert len(report.rows) == 5
    assert all(row['actual'] == row['expected'] for row in report.rows[:-1])


@pytest.mark.skipif(not os.environ.get('ARSIA_TEST_DSN') or not os.environ.get('ARSIA_C_PACKAGE'),
                    reason='Needs A test database and the existing C06 package')
def test_c06_accepts_real_frozen_manifest_but_blocks_incomplete_raw(vic_build, connection, monkeypatch, tmp_path):
    package = Path(os.environ['ARSIA_C_PACKAGE']).resolve()
    monkeypatch.syspath_prepend(str(package / 'src'))
    module = importlib.import_module('arsia_c.person_checks')
    frozen = vic_build[0]
    files = frozen.as_dict()['files']
    count = connection.execute('SELECT count(*) FROM raw.record WHERE resource_id = ANY(%s)',
                               ([f['resource_id'] for f in files],)).fetchone()[0]
    assert count == 0, 'Use an isolated database without the selected official Raw rows'
    reports = module.review_manifest(ModuleConnection(connection), frozen)
    assert len(reports) == 1
    report = reports[0]
    write_evidence(tmp_path / 'c06-empty-raw.json', report)
    assert report['status'] == 'block'
    assert report['reason_counts']['selected_raw_count_mismatch'] == 3
    assert report['policy_checks']['case_set_match'] is False
    assert connection.closed is False
    assert connection.info.transaction_status.name == 'INTRANS'


@pytest.mark.skipif(not os.environ.get('ARSIA_TEST_DSN') or not os.environ.get('ARSIA_C_PACKAGE')
                    or os.environ.get('ARSIA_VIC_CASE_REPLAY') != '1',
                    reason='Opt-in official case excerpt needs C replay tool, original CSV files and isolated PostgreSQL')
def test_registered_case_excerpt_reaches_c06_through_b_manifest(vic_build, monkeypatch, tmp_path):
    from test_manifest import ROOT
    package = Path(os.environ['ARSIA_C_PACKAGE']).resolve()
    monkeypatch.syspath_prepend(str(package / 'src'))
    monkeypatch.setenv('ARSIA_REPOSITORY', str(ROOT))
    spec = importlib.util.spec_from_file_location('vic_case_replay', package / 'tools/replay_c06_cases.py')
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    c06 = importlib.import_module('arsia_c.person_checks')
    frozen = vic_build[0]
    calls = []
    def review(connection, files, analysis, policy):
        assert sorted(files, key=lambda f: f['resource_id']) == frozen.as_dict()['files']
        assert analysis == frozen.as_dict()['analysis']
        assert policy == frozen.as_dict()['rules']['mappings'][0]['content']
        calls.append(True)
        return c06.review_manifest(connection, frozen)[0]
    monkeypatch.setattr(replay, 'review_restricted', review)
    replay.replay(tmp_path / 'c06-frozen-manifest-excerpt.json')
    assert calls == [True]
