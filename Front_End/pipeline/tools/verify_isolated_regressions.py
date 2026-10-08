"""Run DB regressions against an owned acceptance server, preserving test DBs.

The supplied lab must have verify_act_isolated's ownership receipt and marker.
Starts/stops only that stopped container. No live import configuration is read.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import time


def run_new(output, tests, executor_image, storage_policy, adaptation_v1=False):
    """Each module gets a new owned database and a fresh, immutable process binding."""
    import sys
    from collections import defaultdict
    if storage_policy != 'keep-full':
        raise ValueError('Regression evidence is retained; use --storage-policy keep-full')
    from arsia_pipeline.test_session import TestSession
    from arsia_pipeline.storage_lifecycle import atomic_json
    from arsia_pipeline import isolated_executor
    selected = tests or ['pipeline/tests/test_backend.py', 'pipeline/tests/test_autonomous_backend.py']
    modules = defaultdict(list)
    for node in selected:
        modules[node.split('::', 1)[0]].append(node)
    output = output.resolve()
    output.mkdir(parents=True, mode=0o700)
    reports = []
    for index, (module, nodes) in enumerate(modules.items()):
        home = output / f'{index:02d}-{Path(module).stem}'
        session = TestSession.create(home, suite='isolated-db-regressions',
            postgres_image='efedf3595f1d', executor_image=executor_image or isolated_executor.IMAGE,
            keep_full=True)
        session.cfg['dedicated_regression_module'] = True
        session.cfg['autonomous_adaptation_v1'] = adaptation_v1
        runtime = Path(session.cfg['data_root'])/'runtime.json'
        atomic_json(runtime, session.cfg)
        env = dict(os.environ, ARSIA_IMPORT_CONFIG=str(runtime),
            ARSIA_REGRESSION_INSTANCE=session.cfg['instance_id'])
        from psycopg.conninfo import conninfo_to_dict
        password = conninfo_to_dict(session.cfg['dsn'])['password']
        arguments = ['-q', '--tb=short', '-p', 'no:cacheprovider', '--basetemp', str(home/'pytest-tmp'), *nodes]
        tick = time.monotonic(); code = 1
        try:
            completed = subprocess.run([sys.executable, '-m', 'pytest', *arguments], env=env,
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=7200)
            code = completed.returncode
            (home/'pytest.txt').write_text((completed.stdout+completed.stderr).replace(password, '[redacted]'))
            report = {'returncode': code, 'arguments': arguments, 'real_model_calls': 0,
                'wall_seconds': time.monotonic()-tick, 'fresh_process_binding': True,
                'instance_id': session.cfg['instance_id'], 'test_databases_retained': True}
            atomic_json(home/'result.json', report); reports.append(report)
            print(json.dumps({'module': module, 'returncode': code, 'log': str(home/'pytest.txt')}), flush=True)
        finally:
            atomic_json(home/'storage-finalize.json', session.finish(success=code==0))
    atomic_json(output/'result.json', {'modules': reports, 'returncode': max(r['returncode'] for r in reports)})
    return max(r['returncode'] for r in reports)


def run(lab, output, tests=None, executor_image=None):
    if (lab / 'STORAGE-ARCHIVE.json').exists():
        raise RuntimeError('This laboratory is archived: restore its verified package into a NEW owned environment first')
    session_manifest = lab / 'session.json'
    if session_manifest.exists():
        manifest = json.loads(session_manifest.read_text())
        if manifest.get('state') in {'archived','db_archiving','db_verified','db_eviction_pending'}:
            raise RuntimeError('Managed database is archived or maintenance is incomplete; explicit recovery is required')
        raise RuntimeError('Managed sessions must run regressions before their automatic finalizer; closed sessions are not implicitly restarted')
    output.mkdir(parents=True, mode=0o700)
    owner = json.loads((lab / 'ownership.json').read_text())
    original = json.loads((lab / 'lab/runtime.json').read_text())
    actual = json.loads(subprocess.check_output(['docker', 'inspect', owner['container']], text=True))[0]
    assert actual['Config']['Labels'].get('arsia.acceptance') == owner['marker'] == original['instance_id']
    assert not actual['State']['Running'], 'Do not interrupt an active acceptance'
    subprocess.run(['docker', 'start', owner['container']], check=True, capture_output=True)
    started = time.monotonic()
    try:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        import psycopg
        from arsia_pipeline import config
        parts = conninfo_to_dict(original['dsn'])
        parts['port'] = subprocess.check_output(['docker', 'port', owner['container'], '5432/tcp'], text=True).strip().rsplit(':', 1)[1]
        config.ROOT = output.resolve() / 'lab'
        config.ROOT.mkdir()
        config.CONFIG = config.ROOT / 'runtime.json'
        cfg = {k: v for k, v in original.items() if k != 'knowledge_root'}
        cfg.update(dsn=make_conninfo(**parts), data_root=str(config.ROOT), agent_gateway_token='offline-regression-fixture-only')
        config.CONFIG.write_text(json.dumps(cfg))
        config.CONFIG.chmod(0o600)
        os.environ['ARSIA_IMPORT_CONFIG'] = str(config.CONFIG)
        os.environ['ARSIA_KEEP_TEST_DATABASES'] = '1'
        for _ in range(100):
            try:
                with psycopg.connect(cfg['dsn']) as conn:
                    assert conn.execute('SELECT instance_id FROM local_instance').fetchone()[0] == owner['marker']
                break
            except psycopg.OperationalError:
                time.sleep(.2)
        else:
            raise RuntimeError('Owned database unavailable')
        from arsia_pipeline import isolated_executor
        from arsia_pipeline.codex_runtime import CodexRuntime
        isolated_executor.IMAGE = (subprocess.check_output(['docker','image','inspect',executor_image,'--format','{{.Id}}'],text=True).strip()
                                   if executor_image else owner['executor_image'])
        def forbidden(*a, **kw):
            raise AssertionError('Regression must use test doubles; real model calls forbidden')
        # Keep the gateway implementation testable with fake HTTP connections.
        # Block the actual transport at its request boundary instead.
        import http.client
        original_request = http.client.HTTPConnection.request
        def offline_request(connection, method, url, *a, **kw):
            if url in ('/api/imports/agent-model', '/api/imports/codex-model'):
                return forbidden()
            return original_request(connection, method, url, *a, **kw)
        http.client.HTTPConnection.request = offline_request
        CodexRuntime.run = forbidden
        import pytest
        arguments = ['-q', '--tb=short', '-p', 'no:cacheprovider'] + (tests or [
                     'pipeline/tests/test_backend.py', 'pipeline/tests/test_autonomous_backend.py', 'pipeline/tests/test_codex_integration.py'])
        stream = io.StringIO()
        with redirect_stdout(stream), redirect_stderr(stream):
            result = int(pytest.main(arguments))
        log = stream.getvalue().replace(parts['password'], '[redacted]')
        (output / 'pytest.txt').write_text(log)
        report = {'returncode': result, 'wall_seconds': time.monotonic() - started, 'arguments': arguments,
                  'owned_server': owner['name'], 'test_databases_retained': True, 'real_model_calls': 0,
                  'executor_image': isolated_executor.IMAGE,
                  'limits': 'Synthetic DB boundary tests complement but do not replace real-source QA.'}
        (output / 'result.json').write_text(json.dumps(report, indent=2))
        print(log[-5000:])
        return result
    finally:
        assert subprocess.check_output(['docker', 'inspect', owner['container'], '--format',
            '{{index .Config.Labels "arsia.acceptance"}}'], text=True).strip() == owner['marker']
        subprocess.run(['docker', 'stop', owner['container']], check=True, capture_output=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    scope=parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--owned-lab', type=Path)
    scope.add_argument('--new-managed-session',action='store_true')
    parser.add_argument('--storage-policy',choices=['recent-two','keep-full'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--test', action='append', help='Optional focused pytest node; repeat for multiple nodes. Model transports remain forbidden.')
    parser.add_argument('--adaptation-v1',action='store_true',help='Enable reviewed candidate reuse only in the newly created test runtime')
    parser.add_argument('--executor-image', help='Explicit reviewed image override for this test process only')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Use a new evidence directory')
    if args.new_managed_session:
        if not args.storage_policy:parser.error('New session requires --storage-policy')
        raise SystemExit(run_new(args.output,args.test,args.executor_image,args.storage_policy,args.adaptation_v1))
    raise SystemExit(run(args.owned_lab, args.output, args.test, args.executor_image))
