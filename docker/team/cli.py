"""Small Docker entry points around the existing team build and reader."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from http.server import ThreadingHTTPServer
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from docker.team import common


def safe_text(value):
    for key in ('ARSIA_DB_PASSWORD', 'ARSIA_LOADER_PASSWORD', 'ARSIA_READER_PASSWORD'):
        password = os.environ.get(key)
        if password:
            value = value.replace(password, '[redacted]')
    return value


def info():
    image_inputs = ROOT.parent / 'image-inputs.json'
    wheel = ROOT.parent / 'wheels/arsia_native_intake-0.1.0-py3-none-any.whl'
    return {'declared_revision': os.environ.get('ARSIA_IMAGE_REVISION', 'working-tree'),
            'python': platform.python_version(), 'container_architecture': platform.machine(),
            'platform': platform.platform(),
            'image_inputs_sha256': hashlib.sha256(image_inputs.read_bytes()).hexdigest(),
            'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
            'sources': json.loads((ROOT / 'docker/team/sources.json').read_text(encoding='utf-8')),
            'packages': {name: importlib.metadata.version(name) for name in (
                'arsia-native-intake', 'psycopg', 'psycopg-binary', 'openpyxl', 'pytest')},
            'installation': common.check_installation()}


def new_output(command):
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + command + '-' + uuid4().hex[:8]
    return Path('/evidence') / name


def official_files():
    from arsia_ingest.official_definitions import official_definitions
    official_definitions(ROOT)
    catalogue = json.loads((ROOT / 'config/native-inputs.json').read_text(encoding='utf-8'))
    result = []
    for resource in catalogue['resources']:
        path = Path('/official') / Path(resource['path']).name
        if not path.is_file():
            raise ValueError('Missing official file: ' + path.name)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != resource['expected_sha256']:
            raise ValueError('Official file hash differs: ' + path.name)
        result.append({'resource_id': resource['resource_id'], 'filename': path.name,
                       'sha256': digest, 'bytes': path.stat().st_size})
    return {'status': 'passed', 'files': result, 'scope': 'Pinned file identities only; no build performed'}


def build(kind, output):
    from arsia_ingest.build import s0_request, official_request
    from arsia_ingest.pipeline import prepare
    from arsia_ingest.runner import run_build
    common.check_installation()
    if kind == 's0':
        prepared = prepare(ROOT / 'tests/fixtures/s0/config.json', Path('/data/intake/synthetic'))
        factory = s0_request
    else:
        official_files()
        from arsia_ingest.official import prepare_official_inputs
        prepared = prepare_official_inputs('/official', '/data/intake/official', ROOT)
        factory = official_request
    if prepared['status'] != 'prepared':
        raise ValueError('Input preparation failed: ' + str(prepared.get('run_dir')))
    request = factory(connect=lambda: common.connect('loader'), project_root=ROOT,
                      prepared_run=prepared['run_dir'], evidence_root=output / 'build',
                      prepared_by=os.environ['ARSIA_EXECUTOR'])
    result = run_build(**request).as_dict()
    if result['result'] not in {'succeeded', 'no_change'}:
        common.write(output / 'build-result.json', result)
        raise ValueError('Build did not succeed: ' + result['result'])
    return result


def status():
    with common.connect('reader') as connection:
        rows = connection.execute('SELECT dataset_kind,batch_id,switched_at FROM published.current_release ORDER BY dataset_kind').fetchall()
    return {'releases': [{'mode': r[0], 'batch_id': str(r[1]), 'switched_at': r[2].isoformat()} for r in rows]}


def s0_results(batch):
    from arsia_d09.dashboard import DashboardFilters, load_dashboard
    with common.connect('reader') as reader:
        snapshot = load_dashboard(reader, DashboardFilters('synthetic'))
    if str(snapshot.release.batch_id) != batch:
        raise ValueError('Reader did not resolve the published S0 batch')
    metrics = {name: sum(row[name] for row in snapshot.trend if row[name] is not None) for name in (
        'crash_count', 'fatal_crash_count', 'fatality_count', 'casualty_count')}
    metrics.update(unit_count=sum(row['unit_count'] for row in snapshot.units),
                   map_points=len(snapshot.map.points),
                   map_crashes=snapshot.map.coverage['crash_count'])
    with common.connect('loader') as loader:
        metrics['qa_rows'] = loader.execute('SELECT count(*) FROM qa.check_result WHERE batch_id=%s', (batch,)).fetchone()[0]
        metrics['canonical_units'] = loader.execute('SELECT count(*) FROM canonical.unit WHERE batch_id=%s', (batch,)).fetchone()[0]
        manifest = loader.execute('SELECT manifest FROM meta.batch WHERE batch_id=%s', (batch,)).fetchone()[0]
    expected = {'crash_count': 6, 'fatal_crash_count': 2, 'fatality_count': 3, 'casualty_count': 7,
                'unit_count': 6, 'map_points': 4, 'map_crashes': 6, 'qa_rows': 63, 'canonical_units': 6}
    if metrics != expected:
        raise ValueError('S0 values differ: ' + str(metrics))
    return {'metrics': metrics, 'batch_id': batch, 'reader': asdict(snapshot), 'manifest': manifest}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('info', 'init', 's0', 'status', 'serve', 'acceptance',
                                           'official-check', 'official-build', 'recover'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    if args.command == 'serve':
        common.check_installation()
        from arsia_d09.web import make_handler
        print('ARSIA dashboard listening on container port 8765', flush=True)
        ThreadingHTTPServer(('0.0.0.0', 8765), make_handler(common.dsn('reader'), False)).serve_forever()
        return 0
    output = args.output or new_output(args.command)
    if not output.resolve().is_relative_to(Path('/evidence')):
        parser.error('Output must be below /evidence')
    if args.command == 'acceptance':
        from docker.team.acceptance import run
        result = run(output)
        print(json.dumps({'status': result['status'], 'evidence': str(output), 'exit_code': result['exit_code']}))
        return result['exit_code']
    output.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'failed', 'command': args.command, 'started_at': datetime.now(timezone.utc).isoformat(),
               'executor': os.environ.get('ARSIA_EXECUTOR'), 'independent_member_signoff': False,
               'final_platform_accepted': False}
    exit_code = 0
    try:
        if not receipt['executor'] or receipt['executor'].startswith('REPLACE_'):
            raise ValueError('Set ARSIA_EXECUTOR to the actual person running these commands')
        receipt['runtime'] = info()
        if args.command == 'info':
            value = receipt['runtime']
        elif args.command == 'init':
            value = common.initialize()
        elif args.command in {'s0', 'official-build'}:
            value = build('s0' if args.command == 's0' else 'official', output)
            if args.command == 's0':
                value['checked_results'] = s0_results(value['batch_id'])
        elif args.command == 'status':
            value = status()
        elif args.command == 'official-check':
            value = official_files()
        else:
            from arsia_ingest.recovery import recover_run
            if not args.run_dir or not args.run_dir.resolve().is_relative_to(Path('/evidence')):
                raise ValueError('Pass the existing /evidence/.../build/... run directory')
            recovered = recover_run(connect=lambda: common.connect('loader'), run_dir=args.run_dir,
                                    evidence_root=output / 'recovery')
            value, exit_code = recovered.as_dict(), recovered.exit_code
        receipt.update(status='passed' if exit_code == 0 else 'unresolved', result=value)
    except Exception as exc:
        exit_code = 1
        receipt['error'] = {'type': type(exc).__name__, 'message': safe_text(str(exc))}
    receipt['exit_code'] = exit_code
    receipt['finished_at'] = datetime.now(timezone.utc).isoformat()
    (output / 'receipt.json').write_text(safe_text(json.dumps(receipt, indent=2, default=str)) + '\n', encoding='utf-8')
    print(json.dumps({'status': receipt['status'], 'evidence': str(output), 'error': receipt.get('error')}))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
