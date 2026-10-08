"""Common final policy for official and manually reviewed candidates.

Deterministic parser receipts preserve the legacy formats; they do not grant
official registration, arbitrary replacement, or a privileged source prefix.
"""
import hashlib
import json
from pathlib import Path

from .errors import ImportCancelled, NeedsInput, ValidationFailure

VERSION = 'publication-policy-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def input_identity(files):
    # Retain multiplicity; filenames and ephemeral upload IDs are not identity.
    values = sorted((f['sha256'], f['size']) for f in files)
    return digest(values) if values else None


def result_identity(result):
    return digest({k: v for k, v in result.items() if k != 'publication_gate'})


def seal_deterministic(result, files, *, native_bundle=None):
    """Called only by the trusted process_bundle after complete parser QA."""
    from .processing import implementation_identity
    if not result.get('qa') or any(q['status'] != 'pass' and not
            (q['code'] == 'QA07_LOCATION' and q['status'] == 'limited') for q in result['qa']):
        raise ValidationFailure('Deterministic parser did not complete its applicable QA')
    level = 'fixed_native' if native_bundle is not None else 'manual_reviewed'
    if native_bundle is not None and (native_bundle['source_id'] != result['source_id'] or
                                     native_bundle['profile_id'] != result['profile_id']):
        raise ValidationFailure('Frozen source identity differs from parser result')
    if native_bundle is None and result.get('evidence', {}).get('profile', {}).get('confirmed') is not True:
        raise ValidationFailure('Manual candidate requires a reviewed profile')
    paths = {k: result[k] for k in ('canonical_path', 'units_path') if result.get(k)}
    result['publication_gate'] = {'version': VERSION, 'admission_level': level,
        'implementation': implementation_identity(), 'input_identity': input_identity(files),
        'output_hashes': {k: file_hash(p) for k, p in paths.items()},
        'result_identity': result_identity(result), 'qa_scope': 'complete_current_input',
        'official_registration': False, 'deletion_authority': False}


def verify_deterministic(job, result):
    from .processing import implementation_identity, IMPLEMENTATION_AT_LOAD
    gate = result.get('publication_gate', {})
    if gate.get('version') != VERSION or gate.get('admission_level') not in {'fixed_native', 'manual_reviewed'}:
        raise ValidationFailure('Missing current deterministic admission receipt')
    if (gate.get('implementation') != implementation_identity() or
            implementation_identity() != IMPLEMENTATION_AT_LOAD or
            gate.get('result_identity') != result_identity(result)):
        raise ValidationFailure('Deterministic candidate or implementation changed after QA')
    if gate.get('input_identity') != input_identity(job['files']):
        raise ValidationFailure('Publication inputs differ from current QA')
    for f in job['files']:
        p = Path(f['path'])
        if p.is_symlink() or not p.is_file() or p.stat().st_size != f['size'] or file_hash(p) != f['sha256']:
            raise ValidationFailure('Publication input bytes changed after receipt')
    for key, expected in gate['output_hashes'].items():
        p = Path(result[key])
        if p.is_symlink() or not p.resolve().is_relative_to(Path(job['work_dir']).resolve()) or file_hash(p) != expected:
            raise ValidationFailure('Candidate output changed after deterministic QA')
    return gate


def admission_level(result):
    gate = result.get('publication_gate', {})
    if gate.get('version') == VERSION:
        return gate['admission_level']
    # Historical evidence is read under an explicit compatibility rule. No
    # source name/prefix itself grants a level or publication permission.
    if (result.get('admission', {}).get('status') == 'admitted' and
            result.get('source_contract', {}).get('contract_version') == 'canonical-v2'):
        return 'official_admitted'
    if result.get('evidence', {}).get('profile', {}).get('profile_version') == 'generic-v1':
        return 'manual_reviewed'
    if result.get('evidence', {}).get('canonical_sha256') and result.get('evidence', {}).get('source_contract_confirmed') is not None:
        return 'fixed_native'
    return 'legacy_unclassified'


def require_source_level(candidate, previous):
    """Manual source text never inherits official identity in either direction."""
    if not previous:
        return
    old, new = admission_level(previous), admission_level(candidate)
    if (old == 'manual_reviewed') != (new == 'manual_reviewed'):
        raise NeedsInput('Manual and officially admitted sources have separate authority. Use a distinct source_id; a confirmed profile cannot replace an official source.')
    if old == 'legacy_unclassified':
        raise NeedsInput('Historical source admission needs an explicit reviewed compatibility receipt before replacement.')


def require_active_attempt(conn, job):
    row = conn.execute('''SELECT j.status,a.status AS attempt_status,a.finished_at FROM jobs j
        JOIN attempts a ON a.job_id=j.id AND a.number=j.attempt
        WHERE j.id=%s AND a.id=%s''', (job['id'], job['attempt_id'])).fetchone()
    if row and row['status'] in {'cancelled', 'cancel_requested'}:
        raise ImportCancelled()
    if (not row or row['status'] not in {'profiling', 'processing', 'validating', 'publishing'} or
            row['attempt_status'] != 'running' or row['finished_at'] is not None):
        raise ValidationFailure('Only the current active attempt may request publication')


def historical_replay(conn, candidate, base):
    if not base or admission_level(candidate) != 'fixed_native':
        return None
    target = input_identity(candidate.get('files', []))
    if not target:
        return None
    for row in conn.execute('SELECT id,result FROM batches WHERE source_id=%s ORDER BY created_at DESC,id DESC',
                            (candidate['source_id'],)):
        if str(row['id']) != str(base['id']) and input_identity(row['result'].get('files', [])) == target:
            return row['id']
    return None
