#!/usr/bin/env python3
"""Verify all seven pinned official files in an installed wheel and private PG16."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from verify_ac_postgres import main
from verify_d04_lineage_postgres import check_schema


def verify():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-root', type=Path, required=True)
    parser.add_argument('--archive-root', type=Path, required=True)
    parser.add_argument('--prepared-run', type=Path,
                        help='Reuse a complete intake; hashes and all rows are still checked')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--docker')
    args = parser.parse_args()
    for name, value in (('NATIVE_ROOT', args.native_root), ('ARCHIVE_ROOT', args.archive_root),
                        ('PREPARED_RUN', args.prepared_run)):
        key = 'ARSIA_OFFICIAL_' + name
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value.resolve())
    sys.argv[1:] = ['--output', str(args.output)]
    if args.docker:
        sys.argv.extend(['--docker', args.docker])
    check_schema()
    started = time.perf_counter()
    result = main(
        inventory_path='config/build-inventory.json',
        # Start the full snapshot in a clean database, separate from SQL unit fixtures.
        tests=('test_official_build_postgres.py',),
        scope='Pinned NSW/VIC/QLD full snapshots; real B10, E03/E06, QA01–QA07 and reader interface',
        pg_tmpfs=False,
    )
    path = args.output.resolve() / 'summary.json'
    summary = json.loads(path.read_text(encoding='utf-8'))
    summary.update(
        elapsed_seconds=round(time.perf_counter() - started, 3),
        full_official_build_verified=result == 0,
        publication_performed=True if result == 0 else None,
        publication_scope='Private test database using full official snapshots; no shared/public release',
        final_platform_accepted=False,
        boundary='VIC restricted use retained; D09 deferred; independent E acceptance remains separate',
    )
    path.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    raise SystemExit(verify())
