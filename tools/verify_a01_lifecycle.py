#!/usr/bin/env python3
"""Check Compose persistence and A03 logins in a private project."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

from verify_a09_cold_start import AUDIT_PATH, ROOT, digest, find_migrations, psql, run, utc_now


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--docker', default=shutil.which('docker') or 'docker')
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error('Use Python 3.12')
    output = args.output.resolve()
    if output.exists():
        parser.error('Use a new receipt path')
    try:
        import psycopg
        from psycopg import sql
    except ImportError:
        parser.error('Install requirements-db.txt first')
    output.parent.mkdir(parents=True, exist_ok=True)
    migrations = find_migrations()
    project = 'arsia-a01-' + secrets.token_hex(6)
    password = secrets.token_urlsafe(30)
    marker = 'syn_' + secrets.token_hex(8)
    evidence = {
        'contract': 'a01-compose-lifecycle-v1', 'status': 'failed',
        'started_at': utc_now(), 'project': project, 'python': sys.version,
        'git_head': run(['git', '-C', ROOT, 'rev-parse', 'HEAD']).stdout.strip(),
        'working_tree': run(['git', '-C', ROOT, 'status', '--short']).stdout.splitlines(),
        'inputs': [{'path': str(p.relative_to(ROOT)), 'sha256': digest(p)} for p in
                   [ROOT / 'compose.yaml', Path(__file__), AUDIT_PATH, *migrations]],
        'steps': [], 'cleanup': {}, 'scope': 'Private Compose volume and A03 role logins; no platform acceptance',
    }
    # Do not inherit another project's port, password or Compose override.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('COMPOSE_') and k not in {'ARSIA_DB_PASSWORD', 'ARSIA_DB_PORT'}}
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        env_file = Path(temporary) / 'postgres.env'
        env_file.touch(mode=0o600)
        env_file.write_text(f'ARSIA_DB_PASSWORD={password}\nARSIA_DB_PORT=0\n', encoding='utf-8')
        command = [args.docker, 'compose', '--project-name', project,
                   '--file', ROOT / 'compose.yaml', '--env-file', env_file]

        def compose(*arguments):
            return run([*command, *arguments], env=env)

        def container():
            return compose('ps', '-q', 'db').stdout.strip()

        def connect(user):
            port = int(compose('port', 'db', '5432').stdout.strip().rsplit(':', 1)[1])
            return psycopg.connect(host='127.0.0.1', port=port, dbname='arsia',
                                   user=user, password=password, connect_timeout=5)

        def check_marker(step):
            for attempt in range(60):
                try:
                    with connect('arsia_loader') as connection:
                        row = connection.execute(
                            'SELECT jurisdiction_code, source_name, publisher FROM meta.source '
                            'WHERE source_id = %s', (marker,)).fetchone()
                    break
                except psycopg.OperationalError:
                    if attempt == 59:
                        raise
                    time.sleep(0.5)
            require(row == ('TEST', 'A01 lifecycle', 'ARSIA synthetic'), 'Committed marker was lost')
            evidence['steps'].append({'step': step, 'status': 'passed', 'container': container()})

        try:
            evidence['docker'] = run([args.docker, 'version', '--format', '{{.Server.Version}}']).stdout.strip()
            evidence['compose'] = compose('version', '--short').stdout.strip()
            compose('up', '-d', '--wait', 'db')
            original_container = container()
            for migration in migrations:
                psql(args.docker, original_container, migration.read_text(encoding='utf-8'))
            psql(args.docker, original_container, AUDIT_PATH.read_text(encoding='utf-8'))
            with connect('arsia_owner') as connection:
                for role in ('arsia_loader', 'arsia_reader'):
                    connection.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(
                        sql.Identifier(role), sql.Literal(password)))
                settings = connection.execute(
                    "SELECT version(), current_setting('server_encoding'), current_setting('TimeZone')"
                ).fetchone()
                require(settings[0].startswith('PostgreSQL 16.') and settings[1:] == ('UTF8', 'UTC'),
                        'Unexpected PostgreSQL version, encoding or timezone')
                evidence['postgresql'] = settings
            with connect('arsia_loader') as connection:
                require(connection.execute('SELECT current_user').fetchone() == ('arsia_loader',),
                        'Wrong loader login')
                connection.execute('INSERT INTO meta.source VALUES (%s, %s, %s, %s)',
                                   (marker, 'TEST', 'A01 lifecycle', 'ARSIA synthetic'))
                try:
                    with connection.transaction():
                        connection.execute('DELETE FROM meta.source WHERE false')
                except psycopg.errors.InsufficientPrivilege:
                    pass
                else:
                    raise AssertionError('Loader DELETE was allowed')
            with connect('arsia_reader') as connection:
                require(connection.execute('SELECT current_user').fetchone() == ('arsia_reader',),
                        'Wrong reader login')
                connection.execute('SELECT * FROM published.current_release').fetchall()
                try:
                    with connection.transaction():
                        connection.execute('SELECT * FROM meta.source')
                except psycopg.errors.InsufficientPrivilege:
                    pass
                else:
                    raise AssertionError('Reader base-table access was allowed')
            evidence['steps'].append({'step': 'A03 audit and real TCP role logins', 'status': 'passed'})
            check_marker('initial committed write')
            compose('stop', 'db')
            require(run([args.docker, 'inspect', '--format', '{{.State.Running}}', original_container]
                        ).stdout.strip() == 'false', 'Container did not stop')
            compose('start', 'db')
            check_marker('stop then start retains data')
            compose('restart', 'db')
            check_marker('restart retains data')
            compose('down')
            compose('up', '-d', '--wait', 'db')
            require(container() != original_container, 'Expected a new container')
            check_marker('down then up retains named-volume data')
            psql(args.docker, container(), AUDIT_PATH.read_text(encoding='utf-8'))
            evidence['steps'].append({'step': 'A03 audit after recreation', 'status': 'passed'})
            evidence['status'] = 'passed'
        except Exception as error:
            evidence['error'] = {'type': type(error).__name__, 'message': str(error),
                                 'stderr': getattr(error, 'stderr', None)}
        finally:
            try:
                compose('down', '--volumes')
                for resource in ('container', 'volume', 'network'):
                    flags = '-aq' if resource == 'container' else '-q'
                    remaining = run([args.docker, resource, 'ls', flags, '--filter',
                                     f'label=com.docker.compose.project={project}']).stdout.splitlines()
                    require(not remaining, f'Private {resource} cleanup failed: {remaining}')
                evidence['cleanup']['private_project_removed'] = True
            except Exception as error:
                evidence['status'] = 'failed'
                evidence['cleanup'] = {'private_project_removed': False, 'error': str(error)}
            evidence['finished_at'] = utc_now()
            output.write_text(json.dumps(evidence, indent=2).replace(password, '[redacted]') + '\n', encoding='utf-8')
    print(json.dumps({'status': evidence['status'], 'output': str(output),
                      'steps': evidence['steps'], 'cleanup': evidence['cleanup']}))
    return 0 if evidence['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
