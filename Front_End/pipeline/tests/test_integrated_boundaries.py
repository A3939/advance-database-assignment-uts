"""Independent observations of dispatch, polling and packaging boundaries."""
import threading
from types import SimpleNamespace

import pytest

from arsia_pipeline import agent, capability_preflight as cp, worker
from arsia_pipeline.codex_bridge import TaskBridge
from arsia_pipeline.errors import ImportCancelled, NeedsInput


@pytest.mark.parametrize('error_type', ['RuntimeError', 'ValueError', 'OSError', 'UnexpectedError'])
def test_unknown_host_envelope_stops_session_and_bridge(tmp_path, error_type):
    envelope = {'run_id': 'bounded-run', 'status': 'failed', 'error': {
        'origin': 'trusted_host', 'type': error_type, 'message': 'Trusted input integrity failure'}}
    rows = cp.execution_blockers(envelope, operation='run_adapter')
    assert rows[0]['kind'] == cp.classified_blockers(RuntimeError('host'))[0]['kind'] == 'system_fault'
    assert rows[0]['details']['executor_error']['type'] == error_type
    session = agent.AgentSession.__new__(agent.AgentSession)
    session.adaptation_v1, session.ready = True, None
    session.runtime_state, session.contract, session.code = {}, {}, ''
    session.usage, session.errors = {'tool_calls': 0}, {}
    session.check_budget = lambda **kw: None
    session.step = lambda *a: 1
    session.progress = lambda *a, **kw: None
    session.persist = lambda *a: None
    session.finish_step = lambda *a: None
    session._execute_tool = lambda *a: envelope
    bridge = TaskBridge.__new__(TaskBridge)
    bridge.lock, bridge.closed, bridge.terminal = threading.RLock(), threading.Event(), None
    bridge.session, bridge.workspace = session, tmp_path
    (tmp_path/'evidence').mkdir()
    bridge.snapshot = lambda: None
    _, failed = bridge.tool('run_adapter', {'mode': 'sample'})
    assert failed and isinstance(bridge.terminal, NeedsInput)
    assert cp.requires_system_change(bridge.terminal.details)
    with pytest.raises(ValueError, match='no longer'):
        bridge.tool('run_adapter', {'mode': 'sample'})
    assert session.usage['tool_calls'] == 1
    envelope['error']['origin'] = 'adapter'
    assert cp.execution_blockers(envelope, operation='run_adapter')[0]['kind'] == 'adapter_revision'


def test_cancellation_io_depends_on_elapsed_time_not_row_count(monkeypatch):
    clock = [0.0]
    reads = []
    state = {'status': 'processing'}
    monkeypatch.setattr(worker.store, 'get_job', lambda *a, **kw: reads.append(clock[0]) or state)
    health = []
    conn = SimpleNamespace(closed=False, info=SimpleNamespace(transaction_status=0), execute=health.append)
    stop = threading.Event()
    check = worker.CancellationCheck('job', stop, conn, clock=lambda: clock[0])
    for _ in range(100_000): check()
    assert len(reads) == len(health) == 1
    state['status'] = 'cancel_requested'
    clock[0] = .249
    check()
    clock[0] = .25
    with pytest.raises(ImportCancelled): check()
    assert len(reads) == 2
    state['status'] = 'processing'
    check(force=True)
    stop.set()
    with pytest.raises(worker.WorkerInterrupted): check()
    assert len(reads) == 3


def test_closed_lock_is_detected_without_waiting_for_poll(monkeypatch):
    monkeypatch.setattr(worker.store, 'get_job', lambda *a, **kw: {'status': 'processing'})
    conn = SimpleNamespace(closed=False, info=SimpleNamespace(transaction_status=0), execute=lambda *a: None)
    stop = threading.Event()
    check = worker.CancellationCheck('job', stop, conn, clock=lambda: 0)
    check()
    conn.closed = True
    with pytest.raises(worker.WorkerInterrupted): check()
    assert stop.is_set()
