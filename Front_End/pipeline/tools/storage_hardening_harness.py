"""Tool-local acceptance receipts. No production storage policy is implemented here."""
import json
from decimal import Decimal
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4
from storage_test_barrier import read_line
from arsia_pipeline.storage_lifecycle import atomic_json, now, sha

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = PROJECT_ROOT / 'pipeline'
CHILD_SCRIPT = PIPELINE_ROOT / 'tools/storage_hardening_child.py'
CHILD_PYTHON = Path(os.path.abspath(sys.executable))
PHASES = {
    'upload_partial': {'sql_files': 0, 'check_busy': True, 'prekill_apply': True},
    'upload_pending_commit': {'sql_files': 0, 'check_busy': True, 'prekill_apply': True},
    'upload_sql_committed': {'sql_files': 1, 'check_busy': False, 'prekill_apply': False},
}


def require_venv():
    # An isolated source checkout may reuse the installed project environment.
    # Children still use this exact interpreter; never fall back to system Python.
    if sys.prefix == sys.base_prefix or sys.version_info < (3,12):
        raise RuntimeError('Use a Python 3.12+ virtual environment with the pipeline dependencies installed')


def remaining(deadline, local=120):
    seconds = min(local, deadline - time.monotonic())
    if seconds <= 0:
        raise TimeoutError('Original frozen acceptance deadline expired')
    return seconds


def json_value(value):
    # Strict JSON: runtime sessions, paths and datetimes must be explicitly shaped.
    def numeric(item):
        if isinstance(item, Decimal):
            return float(item)  # elapsed SQL numeric, never runtime object stringification
        raise TypeError('Unsupported acceptance result type: ' + type(item).__name__)
    return json.loads(json.dumps(value, allow_nan=False, default=numeric))


def sql_files(session, job_id):
    from arsia_pipeline import store
    wanted = UUID(str(job_id))
    with store.connect(session.cfg) as conn, conn.transaction():
        conn.execute('SET TRANSACTION READ ONLY')
        row = conn.execute('SELECT id,files FROM jobs WHERE id=%s', (wanted,)).fetchone()
    if row is None or str(row['id']) != str(wanted):
        raise AssertionError('Uploaded job missing from this explicit test instance')
    return row['files']


def validate_receipt(session, job_id, receipt, public=None):
    wanted = UUID(str(job_id))
    if public is not None:
        if 'path' in public:
            raise AssertionError('Public upload receipt exposed host path')
        for key in ('id', 'name', 'format', 'size', 'sha256'):
            if receipt.get(key) != public.get(key):
                raise AssertionError('Upload receipt mismatch: ' + key)
    if not receipt.get('path'):
        raise AssertionError('Internal receipt has no stored path')
    if receipt.get('storage_version') and (
            receipt.get('instance_id') != session.cfg['instance_id']
            or str(receipt.get('job_id')) != str(wanted)):
        raise AssertionError('CAS receipt belongs to another instance/job')
    return receipt


def load_internal_receipt(session, job_id, public):
    if 'path' in public:
        raise AssertionError('Public upload receipt exposed host path')
    matches = [f for f in sql_files(session, job_id) if f.get('id') == public['id']]
    if len(matches) != 1:
        raise AssertionError('Expected exactly one persisted upload receipt')
    return validate_receipt(session, job_id, matches[0], public)


class Steps:
    def __init__(self, output, deadline):
        self.output, self.deadline, self.rows = Path(output), deadline, []

    def run(self, name, fn):
        remaining(self.deadline)
        row = {'name': name, 'status': 'running', 'started_at': now()}
        self.rows.append(row)
        atomic_json(self.output / 'steps.json', self.rows)
        tick = time.monotonic()
        try:
            value = json_value(fn())  # assertions belong INSIDE fn
            atomic_json(self.output / (name + '.json'), value)
            row.update(status='pass', evidence=name + '.json', result=value)
            return value
        except BaseException as exc:
            row.update(status='fail', error_type=type(exc).__name__,
                       code=getattr(exc, 'code', None), message=str(exc))
            raise
        finally:
            row.update(ended_at=now(), seconds=time.monotonic() - tick)
            atomic_json(self.output / 'steps.json', self.rows)
            print(name, row['status'], round(row['seconds'], 2), flush=True)


class Children:
    def __init__(self, output, deadline):
        self.output, self.deadline, self.children = Path(output), deadline, []
        self.output.mkdir(mode=0o700, exist_ok=True)

    def save(self, child, state, **fields):
        child['receipt'].update(state=state, updated_at=now(), **fields)
        for key in ('log', 'barrier', 'result'):
            path = self.output / child['receipt'][key]
            if path.is_file():
                child['receipt'][key + '_sha256'] = sha(path)
        child['receipt']['history'].append({'state': state, 'at': now(), **fields})
        atomic_json(child['process_path'], child['receipt'])

    def spawn(self, session, action, phase=None, *, cwd=None, **kwargs):
        remaining(self.deadline)
        require_venv()
        identity = uuid4().hex
        kwargs.setdefault('scenario', self.output.parent.name)
        kwargs.setdefault('request_id', kwargs.get('job') or identity)
        kwargs.setdefault('barrier_timeout', remaining(self.deadline, 90))
        result = self.output / (identity + '.result.json')
        log = self.output / (identity + '.log')
        config = session.ledger.root / 'runtime.json' if session else None
        receipt = {'child_id': identity, 'action': action, 'expected_phase': phase,
                   'instance_id': session.cfg['instance_id'] if session else None,
                   'session_id': session.cfg['test_session_id'] if session else None,
                   'job_id': kwargs.get('job'), 'operation_id': kwargs.get('operation'),
                   'scenario':kwargs['scenario'], 'request_id':kwargs['request_id'],
                   'started_at': now(), 'log': log.name,
                   'barrier': result.with_suffix('.barrier.json').name,
                   'result': result.name, 'pid': None, 'returncode': None, 'history': []}
        child = {'receipt': receipt, 'process_path': self.output / (identity + '.process.json'),
                 'result': result, 'stream': None, 'p': None}
        self.children.append(child)
        self.save(child, 'spawn_intent')
        cmd = [str(CHILD_PYTHON), '-B', str(CHILD_SCRIPT), '--action', action,
               '--output', str(result), '--child-id', identity]
        if config: cmd += ['--config', str(config.absolute())]
        if phase: cmd += ['--phase', phase]
        for key, value in kwargs.items():
            cmd += ['--' + key.replace('_', '-'), str(value)]
        stream = log.open('wb'); log.chmod(0o600); child['stream'] = stream
        ready_read, ready_write = os.pipe()
        cmd += ['--ready-fd', str(ready_write)]
        p = subprocess.Popen(cmd, pass_fds=(ready_write,), stdin=subprocess.PIPE, stdout=stream,
                             stderr=subprocess.STDOUT, cwd=cwd or PROJECT_ROOT,
                             env={**os.environ, 'PYTHONPATH': str(PIPELINE_ROOT),
                                  'PYTHONDONTWRITEBYTECODE': '1'})
        os.close(ready_write)
        child['ready_fd'] = ready_read
        child['p'] = p
        self.save(child, 'spawned', pid=p.pid)
        if phase:
            self.await_ready(child)
        return child

    def await_ready(self, child):
        receipt = child['receipt']
        try:
            actual = read_line(child['ready_fd'], remaining(self.deadline))
        except BaseException as exc:
            self.save(child, 'ready_failed', error_type=type(exc).__name__, message=str(exc))
            raise
        for key in ('child_id','pid','instance_id','session_id','job_id','scenario'):
            if actual.get(key) != receipt.get(key):
                self.save(child,'barrier_rejected',actual_barrier=actual)
                raise AssertionError('Child barrier identity mismatch: '+key)
        if actual['phase'] != receipt['expected_phase'] or actual['request_id'] != receipt['request_id']:
            raise AssertionError('Child barrier phase/request mismatch')
        if receipt.get('operation_id') and actual['operation_id'] != receipt['operation_id']:
            raise AssertionError('Child barrier operation mismatch')
        self.save(child,'barrier_reached',actual_phase=actual['phase'],
                  operation_id=actual.get('operation_id'),actual_barrier=actual)
        return actual

    def release(self, child, close=False):
        actual = child['receipt']['actual_barrier']
        reply = {'command':'CONTINUE', **{key:actual[key] for key in
                  ('barrier_id','child_id','scenario','request_id','phase','occurrence')}}
        self.save(child,'release_intent',release=reply)
        child['p'].stdin.write((json.dumps(reply)+'\n').encode());child['p'].stdin.flush()
        if close: child['p'].stdin.close()
        self.save(child,'release_sent',release=reply)

    def finish(self, child, kill=False):
        p = child['p']; remaining(self.deadline)
        if p.poll() is not None:
            self.save(child, 'exited', returncode=p.wait(), ended_at=now())
            if kill:
                raise AssertionError('Unexpected normal/early exit; no SIGKILL was sent')
        elif kill:
            actual = json.loads((self.output / child['receipt']['barrier']).read_text())
            if p.pid != child['receipt']['pid'] or actual['pid'] != p.pid:
                raise AssertionError('Live parent-owned child identity changed')
            self.save(child, 'signal_intent', signal=signal.SIGKILL)
            p.send_signal(signal.SIGKILL)
            self.save(child, 'signal_sent', signal=signal.SIGKILL)
        elif child['receipt']['expected_phase']:
            self.release(child, close=True)
        code = p.wait(timeout=remaining(self.deadline))
        self.save(child, 'exited', returncode=code, ended_at=now())
        if kill:
            assert code == -signal.SIGKILL
            return json_value(child['receipt'])
        if code:
            raise RuntimeError('Child failed: ' + str(self.output / child['receipt']['log']))
        result = json.loads(child['result'].read_text())
        self.save(child, 'result_saved')
        return result

    def stop(self, allowance=90):
        until = time.monotonic() + allowance; records = []
        for child in self.children:
            p = child['p']
            if p is None: continue
            try:
                if p.poll() is None:
                    p.terminate(); self.save(child, 'cleanup_terminate', signal=signal.SIGTERM)
                    try: p.wait(timeout=remaining(until, 10))
                    except subprocess.TimeoutExpired:
                        p.kill(); self.save(child, 'cleanup_kill', signal=signal.SIGKILL)
                        p.wait(timeout=remaining(until, 10))
                self.save(child, 'exited', returncode=p.wait(), ended_at=now())
                records.append({'child_id': child['receipt']['child_id'], 'stopped': True})
            except Exception as exc:
                records.append({'child_id': child['receipt']['child_id'], 'stopped': False,
                                'error': type(exc).__name__})
            finally:
                if child['stream']: child['stream'].close()
                if child.get('ready_fd') is not None:
                    os.close(child['ready_fd']); child['ready_fd']=None
                if p.stdin and not p.stdin.closed: p.stdin.close()
        return records


def stop_owned_session(session):
    """Normal stop only after production ownership checks; inspection errors persist."""
    from arsia_pipeline.test_session import docker
    m = json.loads((session.ledger.home / 'session.json').read_text())
    if m['state'] == 'archived':
        from arsia_pipeline.storage_restore import inspect_optional
        c = inspect_optional('container', m['docker']['name'])
        v = inspect_optional('volume', m['docker']['volume'])
        if c is not None or v is not None:
            raise AssertionError('Archived resource unexpectedly present')
        return {'session': session.cfg['test_session_id'], 'state': 'archived', 'absent': True}
    _, c, _ = session.own()
    if c['State']['Running']:
        docker('stop', '--time', '30', c['Id'])
        _, c, _ = session.own()
        session.update(state='blocked', maintenance_code='ACCEPTANCE_STOP_PRESERVED')
    assert not c['State']['Running']
    return {'session': session.cfg['test_session_id'], 'container_id': c['Id'],
            'state': json.loads((session.ledger.home / 'session.json').read_text())['state'],
            'running': False, 'volume': m['docker']['volume']}
