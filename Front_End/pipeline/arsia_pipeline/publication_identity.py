"""Publication content identity, independent of exact execution provenance.

Only called after full admission, registration and immutable artifact checks.
This identifies an applied update, not equivalence of arbitrary adapter programs.
"""
import hashlib
import sqlite3
from contextlib import closing

from . import registry
from .errors import ValidationFailure

VERSION = 'publication-content-v1'


def semantics(result):
    from .trusted_qa import semantic_contract
    return {'source_id': result['source_id'],
            'contract': semantic_contract(result['source_contract']),
            'update': result['update'], 'coverage': result['coverage'],
            'capabilities': result['capabilities']}


def identify(result, paths, cancel):
    import json
    # SQLite's temporary database/sort spills to disk for large candidates.
    # Hash every complete canonical row, retaining duplicates and all provenance.
    with closing(sqlite3.connect('')) as db:
        db.execute('CREATE TABLE rows (grain TEXT, digest TEXT)')
        for grain, path in paths.items():
            byte_hash = hashlib.sha256()
            with path.open('rb') as handle:
                for index, line in enumerate(handle):
                    if index % 1000 == 0:
                        cancel()
                    byte_hash.update(line)
                    db.execute('INSERT INTO rows VALUES (?,?)', (grain, registry.digest_json(json.loads(line))))
            if byte_hash.hexdigest() != result['admission']['artifact_hashes'][path.name]:
                raise ValidationFailure('Candidate artifact changed while computing publication identity')
        content = {}
        for grain in sorted(paths):
            h = hashlib.sha256()
            for index, (digest,) in enumerate(db.execute('SELECT digest FROM rows WHERE grain=? ORDER BY digest', (grain,))):
                if index % 1000 == 0:
                    cancel()
                h.update(digest.encode('ascii'))  # fixed-width hashes, unambiguous concatenation
            content[grain] = h.hexdigest()
    value = {'version': VERSION, 'semantics_sha256': registry.digest_json(semantics(result)), 'content_sha256': content}
    from .table_plan import bound_inputs, physical_resources
    admitted = {f.get('id'): f.get('sha256') for f in result.get('files', [])}
    inputs = [(r['role'], i, admitted.get(p['file_id'])) for r in bound_inputs(result['source_contract'])
              for i, p in enumerate(physical_resources(r))]
    replay = registry.digest_json(sorted(inputs)) if inputs and all(v[2] for v in inputs) else None
    return {**value, 'sha256': registry.digest_json(value), 'input_replay_sha256': replay}


def legacy_equivalent(previous, candidate):
    """Conservative bridge for historical batches predating this identity."""
    if previous.get('publication_identity') or not previous.get('source_contract'):
        return False
    hashes = previous.get('admission', {}).get('artifact_hashes')
    return bool(hashes and hashes == candidate['admission']['artifact_hashes']
                and semantics(previous) == semantics(candidate))
