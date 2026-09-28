"""Match Docker inputs to Git commit/tree objects without copying a Git checkout."""
import argparse
import fnmatch
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


PROOF_PATH = 'artifacts/team/build-provenance.objects'
REFERENCE_FILES = {
    'docs/evidence/d09-full-build-validation-2026-09-28/summary.json',
    'docs/evidence/d10-qld-source-query-2026-09-28.json',
    'docs/evidence/d10-postgresql16-validation-2026-09-28.json',
    'docs/evidence/d11-s0-query-results-2026-09-28.json',
    'docs/evidence/d11-final-validation-2026-09-28/acceptance.json',
    'docs/e/e02-interface-register.md',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def object_id(kind, data):
    return hashlib.sha1(kind.encode('ascii') + b' ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def included(name):
    """Keep this closed list in step with .dockerignore."""
    path = PurePosixPath(name)
    leaf = path.name
    if any(part in {'.git', '__pycache__'} for part in path.parts):
        return False
    if any(fnmatch.fnmatchcase(leaf, pattern) for pattern in (
            '.env', '.env.*', '*.pyc', '*.pem', '*.key', 'id_rsa*', 'id_ed25519*')):
        return False
    if len(path.parts) == 1:
        return leaf in {'pyproject.toml', '.dockerignore'} or any(
            fnmatch.fnmatchcase(leaf, p) for p in ('requirements*.txt', 'compose*.yaml'))
    return (path.parts[0] in {'src', 'sql', 'config', 'docker'}
            or (len(path.parts) == 2 and path.parts[0] in {'tests', 'tools'} and leaf.endswith('.py'))
            or name.startswith(('tests/fixtures/', 'docs/sources/evidence/'))
            or name in REFERENCE_FILES)


def read_objects(proof):
    require(Path(proof).is_file(), 'Missing Git proof; run the team prepare-build script before building')
    raw = Path(proof).read_bytes()
    require(len(raw) <= 16 * 1024 * 1024, 'Git metadata proof is too large')
    objects = {}
    offset = 0
    while offset < len(raw):
        end = raw.find(b'\n', offset)
        require(end != -1, 'Truncated Git object header')
        match = re.fullmatch(rb'([0-9a-f]{40}) (commit|tree) ([0-9]+)', raw[offset:end])
        require(match is not None, 'Expected Git commit/tree batch records')
        oid, kind, size = match.groups()
        oid, kind, size = oid.decode('ascii'), kind.decode('ascii'), int(size)
        start, stop = end + 1, end + 1 + size
        require(stop < len(raw) and raw[stop:stop + 1] == b'\n', 'Truncated Git object payload')
        data = raw[start:stop]
        require(object_id(kind, data) == oid, 'Git object hash mismatch: ' + oid)
        require(oid not in objects, 'Duplicate Git object: ' + oid)
        objects[oid] = (kind, data)
        offset = stop + 1
    require(objects, 'Missing Git metadata proof')
    return objects, hashlib.sha256(raw).hexdigest()


def commit_files(objects, revision):
    require(re.fullmatch(r'[0-9a-f]{40}', revision or '') is not None,
            'Use the full 40-character Git commit')
    require(revision in objects and objects[revision][0] == 'commit',
            'Declared revision does not match the prepared Git commit')
    commits = {oid for oid, (kind, _) in objects.items() if kind == 'commit'}
    require(commits == {revision}, 'Expected exactly one Git commit')
    header = objects[revision][1].split(b'\n', 1)[0]
    require(re.fullmatch(rb'tree [0-9a-f]{40}', header) is not None, 'Invalid Git commit tree')
    root_tree = header[5:].decode('ascii')
    used, files = {revision}, {}

    def walk(oid, prefix, ancestors):
        require(oid not in ancestors, 'Recursive Git tree')
        require(oid in objects and objects[oid][0] == 'tree', 'Missing Git tree: ' + oid)
        used.add(oid)
        data, offset, names = objects[oid][1], 0, set()
        while offset < len(data):
            end = data.find(b'\0', offset)
            require(end != -1 and end + 21 <= len(data), 'Truncated Git tree entry')
            entry = data[offset:end].split(b' ', 1)
            require(len(entry) == 2, 'Invalid Git tree entry')
            mode, name = entry
            name = name.decode('utf-8')
            require(name not in {'', '.', '..'} and not any(c in name for c in '/\\\r\n\0'),
                    'Unsafe Git tree path')
            require(name not in names, 'Duplicate Git tree path')
            names.add(name)
            child = data[end + 1:end + 21].hex()
            full = prefix + name
            if mode == b'40000':
                walk(child, full + '/', ancestors | {oid})
            else:
                require(mode in {b'100644', b'100755', b'120000', b'160000'}, 'Unsupported Git tree mode')
                if included(full):
                    require(mode in {b'100644', b'100755'}, 'Only regular build input files are supported: ' + full)
                    files[full] = child
            offset = end + 21

    walk(root_tree, '', set())
    require(used == set(objects), 'Unreferenced Git proof objects')
    return root_tree, files


def verify(root, proof, revision):
    root, proof = Path(root).resolve(), Path(proof).resolve()
    objects, proof_hash = read_objects(proof)
    tree, expected = commit_files(objects, revision)
    actual = {}
    for path in root.rglob('*'):
        require(not path.is_symlink(), 'Symlink in Docker input: ' + str(path.relative_to(root)))
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name == PROOF_PATH and path == proof:
            continue
        actual[name] = path
    missing, extra = sorted(set(expected) - set(actual)), sorted(set(actual) - set(expected))
    require(not missing and not extra,
            f'Docker input paths differ from Git commit; missing={missing[:5]}, extra={extra[:5]}')
    records = []
    for name, path in sorted(actual.items()):
        data = path.read_bytes()
        require(object_id('blob', data) == expected[name],
                'Build input differs from Git commit (check edits or line endings): ' + name)
        records.append({'path': name, 'git_blob_sha1': expected[name],
                        'sha256': hashlib.sha256(data).hexdigest()})
    return {'status': 'verified', 'revision': revision, 'tree': tree,
            'proof_sha256': proof_hash, 'files': records}


def verify_installed(root, revision):
    """Check the verified snapshot again before creating a runtime receipt."""
    root = Path(root)
    record = json.loads((root.parent / 'git-provenance.json').read_text(encoding='utf-8'))
    require(record['status'] == 'verified' and record['revision'] == revision,
            'Runtime revision differs from the verified build')
    for item in record['files']:
        path = root / item['path']
        require(path.is_file() and not path.is_symlink() and
                hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'],
                'Verified runtime input changed: ' + item['path'])
    return {key: value for key, value in record.items() if key != 'files'} | {'input_files': len(record['files'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.root, args.proof, args.revision)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'files'}))
