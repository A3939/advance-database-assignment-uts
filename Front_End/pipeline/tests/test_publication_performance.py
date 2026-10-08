"""Real PostgreSQL regression coverage; the fixture creates a disposable database."""
import threading
import time

import pytest

from test_backend import isolated_database, client, queued, claim_specific
from test_autonomous_backend import candidate, row, published
from arsia_pipeline import agent, publication, query, store, worker
from arsia_pipeline.errors import ValidationFailure


def test_stale_statistics_large_related_batch(client):
    # Establish statistics on an older batch, then COPY a new unseen batch.
    source = 'lookup_scale'
    published(client, source, [row(source, str(i)) for i in range(500)])
    with store.connect() as conn:
        for table, _, _ in publication.ARTIFACTS.values():
            conn.execute('ANALYZE ' + table)
    crashes = [row(source, str(i)) for i in range(4000)]
    units = [row(source, 'u'+str(i), grain='unit', role='unit',
                 relations={'crash': crashes[i % 4000]['record_id']}) for i in range(8000)]
    casualties = [row(source, 'c'+str(i), grain='casualty', role='casualty',
                      relations={'crash': crashes[i]['record_id'], 'unit': units[i]['record_id']}) for i in range(4000)]
    job = claim_specific(queued(client)['id'])
    result = candidate(job, source, crashes, units=units, casualties=casualties)
    start = time.monotonic()
    worker.publish(job, result, lambda: None)
    assert time.monotonic()-start < 15
    saved = store.get_job(job['id'])
    assert saved['status'] == 'succeeded'
    assert saved['result']['database_verification']['orphan_count'] == 0
    assert saved['result']['database_verification']['canonical_unit_count'] == 8000


@pytest.mark.parametrize('fault', ['role', 'record', 'duplicate_across_grains', 'source', 'missing_key'])
def test_indexed_lookup_preserves_rejection_and_atomicity(client, fault):
    source = 'lookup_fault_'+fault
    crash = row(source, 'a')
    unit = row(source, 'u', grain='unit', role='unit', relations={'crash': crash['record_id']})
    if fault == 'role':
        unit['relations'] = {'wrong_role': crash['record_id']}
    elif fault == 'record':
        unit['relations'] = {'crash': '["missing"]'}
    elif fault == 'duplicate_across_grains':
        unit['canonical_id'] = crash['canonical_id']
    elif fault == 'source':
        unit['source_id'] = 'another_source'
    else:
        unit['record_id'] = ''
    job = claim_specific(queued(client)['id'])
    result = candidate(job, source, [crash], units=[unit])
    before = query.catalog()
    with pytest.raises(ValidationFailure):
        worker.publish(job, result, lambda: None)
    assert query.catalog() == before
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0


def test_cancel_interrupts_inflight_sql_and_worker_records_cancelled(client, monkeypatch):
    job = claim_specific(queued(client)['id'])
    result = candidate(job, 'cancel_sql', [row('cancel_sql', 'a')])
    monkeypatch.setattr(agent, 'agent_process', lambda *a, **k: result)
    entered = threading.Event()
    def slow_verify(conn, *a, **k):
        entered.set()
        conn.execute('SELECT pg_sleep(30)')
        raise AssertionError('Cancellation must interrupt the SQL')
    monkeypatch.setattr(publication, 'verify', slow_verify)
    before = query.catalog()
    thread = threading.Thread(target=worker.execute, args=(job, threading.Event()))
    thread.start()
    assert entered.wait(5)
    started = time.monotonic()
    assert client.post(f"/jobs/{job['id']}/cancel").status_code == 200
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert time.monotonic()-started < 5
    assert store.get_job(job['id'])['status'] == 'cancelled'
    assert query.catalog() == before
    with store.connect() as conn:
        assert conn.execute('SELECT status FROM attempts WHERE id=%s', (job['attempt_id'],)).fetchone()['status'] == 'cancelled'
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0
    assert not any(t.name == 'publication-cancel' for t in threading.enumerate())


def test_timeout_rolls_back_and_does_not_leak_connection_setting(client, monkeypatch):
    job = claim_specific(queued(client)['id'])
    result = candidate(job, 'timeout_sql', [row('timeout_sql', 'a')])
    monkeypatch.setattr(publication, 'PUBLICATION_STATEMENT_TIMEOUT_MS', 100)
    monkeypatch.setattr(publication, 'verify', lambda conn, *a, **k: conn.execute('SELECT pg_sleep(30)'))
    before = query.catalog()
    with store.connect() as conn:
        original = conn.execute('SHOW statement_timeout').fetchone()
        started = time.monotonic()
        with pytest.raises(ValidationFailure, match='time limit'):
            worker.publish(job, result, lambda: None, conn)
        assert time.monotonic()-started < 5
        assert conn.execute('SHOW statement_timeout').fetchone() == original
        assert conn.execute('SELECT 1 AS n').fetchone()['n'] == 1
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0
    assert query.catalog() == before
    assert not any(t.name == 'publication-cancel' for t in threading.enumerate())


def test_snapshot_only_verified_once(client, monkeypatch):
    verify = publication.verify
    calls = []
    def counted(*a, **k):
        calls.append(k)
        return verify(*a, **k)
    monkeypatch.setattr(publication, 'verify', counted)
    published(client, 'one_check', [row('one_check', 'a')])
    assert len(calls) == 1
