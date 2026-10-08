"""One bounded row operation: collapse identical retransmissions of a source key.

No value repair, partial-key grouping, conflict selection or numeric allocation.
The adapter ledger is diagnostic until independently replayed by trusted QA.
"""
import hashlib
import json
import sqlite3

from .canonical import stable_json, source_key
from .errors import ValidationFailure

VERSION = 'exact-duplicate-lineage-v1'
PLAN = {'operation': 'collapse_exact_duplicates',
        'equality': 'complete_key_and_all_raw_fields',
        'count_policy': 'one_per_complete_source_key'}


def enabled(resource):
    if 'preprocessing' not in resource:
        return False
    if resource['preprocessing'] != PLAN:
        raise ValidationFailure('Preprocessing requires the exact reviewed duplicate-collapse plan')
    if resource.get('lookups') or resource.get('grain') == 'observation':
        raise ValidationFailure('Duplicate collapse is limited to source records without lookup or aggregate allocation')
    return True


def raw_hash(raw):
    return hashlib.sha256(stable_json(raw).encode()).hexdigest()


def disposition(role, locator, key, raw, representative):
    return {'version': VERSION, 'role': role, 'row_locator': locator,
            'record_id': key, 'raw_sha256': raw_hash(raw),
            'destination_locator': representative,
            'disposition': 'retained' if locator == representative else 'exact_duplicate',
            'count_allocation': 1 if locator == representative else 0}


class AdapterRows:
    """Disk-backed key index, bounded by the existing executor disk/wall budget."""
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.executescript('PRAGMA temp_store=FILE; PRAGMA cache_size=-4096; '
                             'CREATE TABLE seen(role TEXT,key TEXT,raw TEXT,locator TEXT,PRIMARY KEY(role,key));')

    def row(self, contract, resource, locator, raw):
        key = source_key(raw, resource['key'], contract)
        value = stable_json(raw)
        previous = self.db.execute('SELECT raw,locator FROM seen WHERE role=? AND key=?',
                                   (resource['role'], key)).fetchone()
        if previous:
            if previous[0] != value:
                raise ValidationFailure('Conflicting raw values for the same complete source key')
            representative = json.loads(previous[1])
        else:
            self.db.execute('INSERT INTO seen VALUES(?,?,?,?)',
                            (resource['role'], key, value, stable_json(locator)))
            representative = locator
        return disposition(resource['role'], locator, key, raw, representative), previous is None

    def close(self):
        self.db.close()
