"""Trusted bounded subprocess barriers; no hook exposed to uploaded code/API."""
import argparse
import importlib.metadata
import json
import os
import sys
from pathlib import Path
from arsia_pipeline.storage_lifecycle import atomic_json, now

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main(a):
    a.output = a.output.absolute()
    if a.action == 'barrier-probe':
        from storage_barrier_probe import run
        return run(a)
    if a.action == 'probe':
        import fastapi, httpx, psycopg
        from arsia_pipeline import api, input_store, upload_gc, storage_restore, storage_catalog
        assert sys.prefix != sys.base_prefix and sys.version_info >= (3,12)
        result = {'probe': 'pass', 'python': sys.version.split()[0],
                  'executable': os.path.abspath(sys.executable), 'prefix': sys.prefix,
                  'project_root': str(PROJECT_ROOT), 'script': str(Path(__file__).absolute()),
                  'packages': {k: importlib.metadata.version(k) for k in ('fastapi', 'httpx', 'psycopg')},
                  'database_created': False, 'docker_created': False}
        atomic_json(a.output, result)
        return
    if a.config is None or not a.config.is_absolute():
        raise ValueError('Non-probe actions require explicit absolute private configuration')
    from arsia_pipeline.test_session import TestSession
    from verify_storage_isolated import configure
    cfg = json.loads(a.config.read_text()); s = TestSession(cfg)
    from arsia_pipeline.storage_lifecycle import validate_managed
    validate_managed(cfg)
    if Path(cfg['data_root']) / 'runtime.json' != a.config:
        raise ValueError('Private configuration path does not match enrolled instance')

    reservation_operation={}

    from storage_test_barrier import RequestBarrier
    rendezvous = RequestBarrier(output=a.output, phase=a.phase, ready_fd=a.ready_fd,
        timeout=a.barrier_timeout, occurrence=a.occurrence,
        identity={'child_id':a.child_id,'scenario':a.scenario,
                  'instance_id':cfg['instance_id'],'session_id':cfg['test_session_id'],'job_id':a.job})
    def barrier(phase):
        kind = 'upload' if a.action == 'upload' else 'restore'
        ops = s.ledger.operations(kind) if a.action in {'upload', 'restore'} else []
        if a.action == 'upload': ops = [x for x in ops if x['job_id'] == a.job]
        op = reservation_operation.get('operation_id') or (ops[-1]['operation_id'] if ops else a.operation)
        rendezvous(phase, request_id=a.request_id or a.job or a.child_id, operation_id=op)

    from arsia_pipeline import storage_reservations
    def operation_hook(phase,payload):
        reservation_operation.update(payload)
        atomic_json(a.output.with_suffix('.operation-intent.json'),payload)
        barrier(payload['kind']+'_reserved' if phase=='reserved' else phase)
    storage_reservations._TEST_OPERATION_HOOK=operation_hook
    from arsia_pipeline import trusted_helpers
    def helper_hook(phase,intent):
        atomic_json(a.output.with_suffix('.helper-intent.json'),intent)
        barrier(phase)
    trusted_helpers._TEST_HELPER_HOOK=helper_hook
    configure(s)
    if a.action == 'upload':
        from arsia_pipeline import api
        from fastapi.testclient import TestClient
        api._TEST_STORAGE_HOOK = barrier
        with TestClient(api.app) as client:
            response = client.put('/jobs/' + a.job + '/files',
                                  params={'filename': a.payload.name}, content=a.payload.read_bytes())
            response.raise_for_status(); result = {'status': response.status_code}
    elif a.action == 'restore':
        from arsia_pipeline.storage_restore import RestoreOperation
        from arsia_pipeline.storage_lifecycle import StorageError
        original = RestoreOperation.cleanup
        try:
            if a.inject_cleanup_fault:
                def fault(*args, **kwargs):
                    raise StorageError('STORAGE_TEST_CLEANUP', 'bounded cleanup failure')
                RestoreOperation.cleanup = fault
            result = s.restore_database(purpose=a.purpose, pin=a.pin, hook=barrier)
        finally:
            RestoreOperation.cleanup = original
    elif a.action == 'reconcile-restore': result = s.reconcile_restore(a.operation)
    elif a.action == 'reconcile-reservations':
        from arsia_pipeline.storage_catalog import TestSpace
        result=storage_reservations.reconcile(TestSpace(cfg['storage_space']),apply=True)
    elif a.action == 'archive-live-helper':
        from storage_backup_probe import archive_with_live_helper
        result=archive_with_live_helper(s,barrier,a.output)
    elif a.action == 'archive':result=s.archive_database()
    elif a.action == 'create':
        if not a.home or not a.home.is_absolute():raise ValueError('Explicit prospective home required')
        created=TestSession.create(a.home,suite='creation-boundary',postgres_image=s.ledger.session['docker']['image'],
            executor_image=s.ledger.session['docker']['executor_image'],space=cfg['storage_space'])
        result={'created_session':created.cfg['test_session_id'],'home':str(created.ledger.home)}
    elif a.action == 'gc':
        from datetime import datetime, timezone, timedelta
        from arsia_pipeline.upload_gc import reconcile
        result = reconcile(cfg, apply=True, clock=datetime.now(timezone.utc) + timedelta(days=2))
    else:
        from arsia_pipeline import storage_catalog
        storage_catalog._TEST_CLAIM_HOOK = lambda identity: barrier('retention_claimed')
        result = s.finish(success=True) if a.action == 'finalize' else s.apply_retention()
    atomic_json(a.output, result)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--config', type=Path)
    p.add_argument('--action', choices=['barrier-probe','probe','upload','restore','reconcile-restore','gc','finalize','retention','reconcile-reservations','archive','archive-live-helper','create'], required=True)
    p.add_argument('--ready-fd',type=int)
    p.add_argument('--scenario',default='standalone')
    p.add_argument('--request-id')
    p.add_argument('--barrier-timeout',type=float,default=90)
    p.add_argument('--occurrence',type=int,default=1)
    p.add_argument('--probe-chunks',type=int,default=3)
    p.add_argument('--probe-requests',type=int,default=1)
    p.add_argument('--home',type=Path)
    p.add_argument('--phase'); p.add_argument('--job'); p.add_argument('--payload', type=Path)
    p.add_argument('--operation'); p.add_argument('--child-id', required=True)
    p.add_argument('--purpose', choices=['verify_only','restore_for_use'], default='verify_only')
    p.add_argument('--pin'); p.add_argument('--inject-cleanup-fault', choices=['yes'])
    p.add_argument('--output', type=Path, required=True)
    main(p.parse_args())
