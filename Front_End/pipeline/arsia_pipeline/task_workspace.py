"""Portable task evidence and proposals. Files never grant QA/publication authority.

This is a handoff format, not an OS sandbox. The Codex execution boundary must be
verified separately before allowing generated shell commands on a host.
"""
import hashlib
import json
import os
import stat
from pathlib import Path, PurePosixPath


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n').encode()


def safe_file(root, name, *, exists=True):
    base = Path(root)
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(p in {'.', '..'} for p in path.parts) or '\\' in name:
        raise ValueError('Use a relative task file path without traversal')
    if base.is_symlink() or not base.is_dir():
        raise ValueError('Task root must be a real directory')
    current = base
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Task paths cannot contain symbolic links')
    if exists and (not current.is_file() or current.stat().st_nlink != 1):
        raise ValueError('Task file must be a regular unlinked file')
    if not current.resolve().is_relative_to(base.resolve()):
        raise ValueError('Task file escaped its boundary')
    return current


def read_file(root, name, max_bytes):
    """Hold directory descriptors so a changed symlink cannot escape the task."""
    safe_file(root, name)
    descriptors = []
    try:
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(parent)
        parts = PurePosixPath(name).parts
        for part in parts[:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, 'rb') as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > max_bytes:
                raise ValueError('Task file exceeds its size or link boundary')
            content = handle.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError('Task file grew past its bound')
            return content
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def create_workspace(destination, *, contract, code, diagnostics, steps, documents, sdk, policy, identity):
    from .agent import safe
    root = Path(destination)
    # Never merge with another task or overwrite a prior evidence package.
    if root.exists() or root.is_symlink():
        raise ValueError('Use a fresh task workspace; old evidence is preserved')
    if any(p.is_symlink() for p in root.parents):
        raise ValueError('Workspace parent cannot be a symbolic link')
    root.mkdir(parents=True, mode=0o700)
    (root/'proposals').mkdir(mode=0o700)
    files = {
        'evidence/contract.json': _json(safe(contract)),
        'evidence/adapter.py': code.encode(),
        'evidence/unresolved-diagnostics.json': _json(safe(diagnostics)),
        'evidence/tool-results.json': _json(safe(steps)),
        'evidence/policy.json': _json(policy),
        'evidence/identity.json': _json(identity),
        'evidence/SDK.md': sdk.encode(),
    }
    for document_id, text in documents.items():
        # Index names by hash; never treat source IDs as filesystem paths.
        key = hashlib.sha256(document_id.encode()).hexdigest()
        files['evidence/documents/'+key+'.json'] = _json({'document_id':document_id,'text':text,'untrusted_evidence':True})
    if sum(map(len, files.values())) > 256*1024**2:
        raise ValueError('Task evidence package exceeds 256 MiB; original evidence remains in the database')
    index = {}
    for name, content in files.items():
        path = safe_file(root, name, exists=False)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, 'wb') as out:
            out.write(content)
        index[name] = {'sha256':hashlib.sha256(content).hexdigest(), 'bytes':len(content)}
    manifest = {'format':'arsia-task-workspace-v1','identity':identity,'files':index,
        'proposal_contract':'proposals/contract.json','proposal_adapter':'proposals/adapter.py',
        'authority':'Evidence and proposals only. Host-controlled validation, sample/full QA and transactional publication remain mandatory.',
        'execution_ready':False, 'execution_note':'This package is not an OS sandbox or a configured Codex worker.'}
    (root/'manifest.json').write_bytes(_json(manifest)); (root/'manifest.json').chmod(0o400)
    return manifest


def read_evidence(root, name, offset=0, max_chars=16000):
    if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 100 <= max_chars <= 32000:
        raise ValueError('Invalid task evidence pagination')
    manifest = json.loads(read_file(root, 'manifest.json', 1024*1024))
    if name not in manifest['files']:
        raise ValueError('Only indexed evidence files can be read')
    path = safe_file(root, name)
    expected = manifest['files'][name]
    if path.stat().st_size != expected['bytes']:
        raise ValueError('Task evidence changed after export')
    data = read_file(root, name, min(expected['bytes'], 256*1024**2))
    if hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise ValueError('Task evidence hash mismatch')
    text = data.decode('utf-8')
    return {'text':text[offset:offset+max_chars], 'offset':offset,'total_chars':len(text),
        'next_offset':offset+max_chars if offset+max_chars < len(text) else None,
        'sha256':expected['sha256'],'untrusted_evidence':True}


def read_proposal(root):
    contract_path, code_path = safe_file(root, 'proposals/contract.json'), safe_file(root, 'proposals/adapter.py')
    if contract_path.stat().st_size > 512000 or code_path.stat().st_size > 200000:
        raise ValueError('Task proposal exceeds admission size limits')
    contract, code = json.loads(read_file(root, 'proposals/contract.json', 512000)), read_file(root, 'proposals/adapter.py', 200000).decode('utf-8')
    if not isinstance(contract, dict) or not code.strip():
        raise ValueError('A contract object and nonempty adapter are required')
    return contract, code


def admit_proposal(session, root, *, expected_contract_sha256, expected_code_sha256):
    """Called only by the trusted owning worker, never by a standalone file tool."""
    from .registry import digest_json
    if digest_json(session.contract) != expected_contract_sha256 or hashlib.sha256(session.code.encode()).hexdigest() != expected_code_sha256:
        raise ValueError('Host task changed; reread the current contract and adapter before submitting')
    contract, code = read_proposal(root)
    # Normal source identity, evidence IDs and native-source protections apply.
    result = session.execute_tool('set_source_contract', {'contract':contract})
    version = session.execute_tool('write_adapter', {'code':code,'reason':'Task workspace proposal'})
    return {'contract':result, 'adapter':version, 'status':'proposed_requires_fresh_sample_and_full_qa'}
