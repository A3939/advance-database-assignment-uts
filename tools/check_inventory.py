#!/usr/bin/env python3
"""Check inventory and Docker source hashes without modifying any files."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_inventory(root: Path) -> list[str]:
    root = root.resolve()
    errors = []

    def safe_path(name):
        if not isinstance(name, str) or Path(name).is_absolute():
            raise ValueError('expected a relative file path')
        path = root / name
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError('unsafe file path')
        return path

    def check_record(record, label, key='path'):
        try:
            name = record[key]
            path = safe_path(name)
            if not path.is_file():
                errors.append(f'{label}: missing {name}')
            elif hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
                errors.append(f'{label}: checksum mismatch: {name}')
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f'{label}: invalid record ({exc})')

    inventories = sorted((root / 'config').glob('*-inventory.json'))
    for required in ('build-inventory.json', 'd09-inventory.json'):
        if root / 'config' / required not in inventories:
            errors.append(f'missing required inventory: config/{required}')
    for path in [*inventories, root / 'docker/team/sources.json']:
        label = path.relative_to(root).as_posix()
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('expected JSON object')
            groups = ('files', 'overlays') if path.name == 'sources.json' else ('code_files', 'schema_files')
            for group in groups:
                records = data.get(group, [])
                if not isinstance(records, list):
                    raise ValueError(f'{group} must be a list')
                for record in records:
                    if group == 'overlays':
                        check_record(record, label, 'source_path')
                        target = safe_path(record['path'])
                        if target.exists():
                            errors.append(f'{label}: overlay target already exists: {record["path"]}')
                    else:
                        check_record(record, label)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f'{label}: cannot validate ({exc})')
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    errors = check_inventory(args.root)
    if errors:
        print('\n'.join(errors))
        print('\nReview each changed file. For intended runtime changes, run '
              '`python tools/update_build_inventory.py`, review the diff, and commit. '
              'Restore missing files or changed vendored inputs from their declared revision.')
        return 1
    print('Inventory checks passed, including Docker overlay source files.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
