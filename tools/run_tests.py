#!/usr/bin/env python3
"""Run pytest, retain a timestamped JUnit report and atomically publish latest."""
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import subprocess
import sys
import uuid
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main():
    args = sys.argv[1:]
    if args[:1] == ['--']:
        args = args[1:]
    if any(arg.startswith(('--junitxml', '--junit-xml')) for arg in args):
        raise SystemExit('This runner manages --junitxml; omit that argument.')
    directory = ROOT / 'artifacts/test-results'
    directory.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    run_id = started.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    pending = directory / (run_id + '.pending')
    command = [sys.executable, '-m', 'pytest', *args]
    revision = git('rev-parse', 'HEAD')
    dirty = bool(git('status', '--porcelain'))
    code = subprocess.call([*command, '--junitxml=' + str(pending)], cwd=ROOT)
    if not pending.exists():
        ET.ElementTree(ET.Element('testsuites')).write(pending, encoding='utf-8')
    tree = ET.parse(pending)
    props = ET.SubElement(tree.getroot(), 'properties')
    metadata = {
        'revision': revision, 'dirty': str(dirty).lower(), 'python': platform.python_version(),
        'command': ' '.join(command), 'started': started.isoformat(),
        'finished': datetime.now(timezone.utc).isoformat(), 'exit_code': str(code),
        'completed': str(code in (0, 1)).lower(),
    }
    for name, value in metadata.items():
        ET.SubElement(props, 'property', name='arsia.' + name, value=value)
    tree.write(pending, encoding='utf-8', xml_declaration=True)
    history = directory / ('run-' + run_id + '.xml')
    os.replace(pending, history)
    temporary = directory / (run_id + '.latest')
    temporary.write_bytes(history.read_bytes())
    os.replace(temporary, directory / 'latest.xml')
    print('Saved test report:', history.relative_to(ROOT))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
