"""Host watchdog and dispatch accounting; no paid model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from arsia_pipeline import codex_resources as resources
from arsia_pipeline.codex_bridge import TaskBridge
from arsia_pipeline.errors import NeedsInput, BudgetExhausted


def test_cpu_accounting_retains_disappeared_children(monkeypatch):
    previous = {}
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: '1 42 100 00:01.50\n2 42 20 00:00.40\n3 99 999 05:00\n')
    assert resources.group_usage(42, previous) == {'cpu_seconds':1.9,'rss_bytes':120*1024,'processes':2}
    monkeypatch.setattr(subprocess, 'check_output', lambda *a, **k: '1 42 100 00:02.50\n')
    assert resources.group_usage(42, previous)['cpu_seconds'] == 2.9
    assert resources.cpu_seconds('1-02:03:04') == 93784


def test_storage_never_follows_external_symlink_and_rejects_growth(tmp_path):
    root = tmp_path/'task'; root.mkdir()
    outside = tmp_path/'private'; outside.write_bytes(b'x'*100)
    (root/'link').symlink_to(outside)
    assert resources.storage_bytes([root], 5) == 0
    (root/'out').write_bytes(b'x'*6)
    with pytest.raises(ValueError, match='runtime_storage'): resources.storage_bytes([root], 5)


@pytest.mark.parametrize('limit,script,expected',[
    (.2,'import time; time.sleep(20)','wall_seconds'),
    (10,'while True: pass','compute_seconds'),
])
def test_actual_supervisor_stops_own_child(tmp_path, limit, script, expected):
    from arsia_pipeline import codex_supervisor
    receipt = tmp_path/'receipt.json'
    command = [sys.executable, str(Path(codex_supervisor.__file__)), '--parent',str(os.getpid()),
               '--seconds',str(limit),'--cpu-seconds','.1','--receipt',str(receipt),
               '--storage-root',str(tmp_path),sys.executable,'-c',script]
    result = subprocess.run(command, capture_output=True, timeout=9)
    assert result.returncode == 124, result.stderr.decode()
    saved = json.loads(receipt.read_text())
    assert saved['limit'] == expected
    with pytest.raises(ProcessLookupError): os.killpg(saved['group'], 0)


def bridge():
    b = object.__new__(TaskBridge); b.lock=threading.RLock(); b.native_calls=set(); b.terminal=None
    s = SimpleNamespace(bounded_repair_v1=True, usage={'tool_calls':0})
    def budget():
        if s.usage['tool_calls'] >= 2: raise BudgetExhausted('tools')
    s.check_budget=budget; s.step=lambda *a:1; s.finish_step=lambda *a:None; s.persist=lambda:None
    b.session=s
    return b


def event(ident, namespace='functions', name='exec'):
    return {'type':'response.output_item.added','item':{'type':'custom_tool_call','call_id':ident,'namespace':namespace,'name':name}}


def test_dispatch_budget_charged_before_execution_and_once_per_call():
    b=bridge()
    b.guard_model_event(event('a', None)); b.guard_model_event(event('a', None))
    assert b.session.usage['tool_calls']==1
    b.guard_model_event(event('b'))
    with pytest.raises(BudgetExhausted): b.guard_model_event(event('c'))
    assert 'c' not in b.native_calls


@pytest.mark.parametrize('namespace,name',[('collaboration','spawn_agent'),('functions','exec_command'),('clock','sleep'),(None,'self_grant')])
def test_other_native_authorities_blocked_before_dispatch(namespace,name):
    b=bridge()
    with pytest.raises(NeedsInput): b.guard_model_event(event('bad', namespace, name))
    assert b.terminal.code=='TASK_ACTION_BOUNDARY' and not b.native_calls
