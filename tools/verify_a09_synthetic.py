#!/usr/bin/env python3
"""Install a pinned B wheel in a fresh venv and replay the real S0 build."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from verify_a09_cold_start import ROOT, digest, find_migrations, run, utc_now


B_COMMIT = '562de2910bfd7be276b3036983e5680d436fde1e'
REPOSITORY = 'git@github.com:A3939/advance-database-assignment-uts.git'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repository', default=REPOSITORY,
                        help='Git clone URL; default uses the team repository over SSH')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error('Use Python 3.12')
    out = args.output.resolve()
    if out.exists():
        parser.error('Use a new output directory')
    out.mkdir(parents=True)
    checkout = out / 'runtime'
    python = out / 'venv/bin/python'
    evidence = {
        'contract': 'a09-installed-synthetic-cold-start-v1', 'status': 'failed',
        'started_at': utc_now(), 'python': sys.version, 'runtime_commit': B_COMMIT,
        'a_checkout': run(['git', '-C', ROOT, 'rev-parse', 'HEAD']).stdout.strip(),
        'a_working_tree': run(['git', '-C', ROOT, 'status', '--short']).stdout.splitlines(),
        'verifier_sha256': digest(Path(__file__)), 'commands': [],
        'a_requirements': [{'path': p.name, 'sha256': digest(p)}
                           for p in sorted(ROOT.glob('requirements*.txt'))],
        'scope': 'B-assisted A09 replay from a fresh clone, venv and private PostgreSQL database',
        'final_platform_accepted': False,
        'not_executed': 'Official publication, dashboard and independent E09 acceptance',
    }
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('ARSIA_', 'AC_TEST_', 'PG', 'PYTHON', 'PIP_'))
           and k not in {'VIRTUAL_ENV', 'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE'}}
    env.update(GIT_LFS_SKIP_SMUDGE='1', PYTHONDONTWRITEBYTECODE='1', PIP_DISABLE_PIP_VERSION_CHECK='1')

    def execute(*arguments):
        index = len(evidence['commands']) + 1
        log = out / f'{index:02d}.log'
        with log.open('w', encoding='utf-8') as stream:
            result = subprocess.run([str(a) for a in arguments], cwd=out, env=env,
                                    stdout=stream, stderr=subprocess.STDOUT, text=True)
        evidence['commands'].append({'argv': [str(a) for a in arguments],
                                     'exit_code': result.returncode, 'log': log.name})
        if result.returncode:
            raise RuntimeError(f'Command {index} failed; see {log.name}')

    try:
        execute('git', 'clone', '--no-checkout', args.repository, checkout)
        execute('git', '-C', checkout, 'checkout', '--detach', B_COMMIT)
        if run(['git', '-C', checkout, 'rev-parse', 'HEAD']).stdout.strip() != B_COMMIT:
            raise ValueError('Wrong runtime checkout')
        schema = [*find_migrations(), ROOT / 'sql/tests/a03_database_roles.sql']
        for path in schema:
            relative = path.relative_to(ROOT)
            if path.read_bytes() != (checkout / relative).read_bytes():
                raise ValueError('Pinned B schema differs from A: ' + str(relative))
        evidence['a_schema'] = [{'path': str(p.relative_to(ROOT)), 'sha256': digest(p)} for p in schema]
        execute(sys.executable, '-m', 'venv', out / 'venv')
        execute(python, '-m', 'pip', 'install', '-r', checkout / 'requirements-db.txt',
                '-r', ROOT / 'requirements-db.txt')
        execute(python, '-m', 'pip', 'wheel', '--no-build-isolation', '--no-deps',
                '--wheel-dir', out / 'wheels', checkout)
        wheels = list((out / 'wheels').glob('*.whl'))
        if len(wheels) != 1:
            raise ValueError('Expected one project wheel')
        execute(python, '-m', 'pip', 'install', '--no-deps', wheels[0])
        execute(python, '-m', 'pip', 'check')
        evidence['wheel'] = {'name': wheels[0].name, 'sha256': digest(wheels[0])}
        evidence['packages'] = json.loads(run([python, '-m', 'pip', 'list', '--format=json'], env=env).stdout)
        execute(python, checkout / 'tools/verify_full_build_postgres.py', '--output', out / 'full-build')
        summary = json.loads((out / 'full-build/summary.json').read_text(encoding='utf-8'))
        if not summary.get('full_s0_build_verified') or summary.get('final_platform_accepted') is not False:
            raise ValueError('Missing S0 success or incorrect acceptance boundary')
        evidence['build_summary'] = summary
        evidence['build_cleanup'] = json.loads((out / 'full-build/cleanup.json').read_text(encoding='utf-8'))
        evidence['build_inputs_sha256'] = digest(out / 'full-build/inputs.json')
        evidence['status'] = 'passed'
    except Exception as error:
        evidence['error'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        evidence['finished_at'] = utc_now()
        (out / 'receipt.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': evidence['status'], 'receipt': str(out / 'receipt.json'),
                      'error': evidence.get('error'), 'build_summary': evidence.get('build_summary')}))
    return 0 if evidence['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
