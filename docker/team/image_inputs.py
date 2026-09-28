"""Check copied origins, overlay E tests and record the actual image inputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil

from provenance import verify_installed

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    verify_installed(ROOT, os.environ.get('ARSIA_IMAGE_REVISION', ''))
    sources = json.loads((ROOT / 'docker/team/sources.json').read_text(encoding='utf-8'))
    for row in sources['files']:
        if digest(ROOT / row['path']) != row['sha256']:
            raise ValueError('Changed upstream file: ' + row['path'])
    for row in sources['overlays']:
        source, target = ROOT / row['source_path'], ROOT / row['path']
        if target.exists():
            raise ValueError('Refusing to replace a B file: ' + row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    inputs = [{'path': p.relative_to(ROOT).as_posix(), 'sha256': digest(p)}
              for p in sorted(ROOT.rglob('*')) if p.is_file()]
    (ROOT.parent / 'image-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
