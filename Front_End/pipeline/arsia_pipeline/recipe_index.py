"""Disposable per-instance recipe index. Registry and fresh QA remain authoritative.

Template identity excludes run-local IDs, registry version IDs and receipt paths.
Each promotion records a separate audit; repeated runs do not widen searches.
Legacy CAS objects are indexed once, in bounded objects, without deleting them.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .source_knowledge import digest


def exact_key(resources):
    return digest(sorted({(r['sha256'], r['size']) for r in resources}))


def template_key(record):
    from .registry import normalized_contract
    return digest({'contract': normalized_contract(record['contract']),
                   'resources': [{k: v for k, v in r.items() if k != 'file_id'} for r in record['resources']],
                   'documents': sorted({(d.get('url'), d.get('sha256')) for d in record['documents']}),
                   'supplements': record.get('supplement_hashes', []),
                   'dependencies': record['dependencies'], 'image': record['image'],
                   'dependency_scope': record.get('dependency_scope'),
                   'binding_files': sorted((f.get('evidence_url'),f['sha256']) for f in record.get('binding_files',[])),
                   'version_candidate': record.get('version_candidate')})


class RecipeIndex:
    def __init__(self, store, instance):
        self.store, self.instance = store, instance
        self.path = store.root.parent / 'recipes.sqlite'

    @contextmanager
    def connect(self):
        if self.path.is_symlink():
            raise ValueError('Recipe index cannot be a symlink')
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA busy_timeout=5000')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS templates(id TEXT PRIMARY KEY, object_sha TEXT NOT NULL, exact_key TEXT NOT NULL, resource_count INTEGER NOT NULL, version_eligible INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS template_inputs ON templates(exact_key);
                CREATE INDEX IF NOT EXISTS template_versions ON templates(version_eligible,resource_count);
                CREATE TABLE IF NOT EXISTS fields(template_id TEXT NOT NULL, field TEXT NOT NULL, PRIMARY KEY(field,template_id));
                CREATE TABLE IF NOT EXISTS audits(id TEXT PRIMARY KEY, template_id TEXT NOT NULL, registry_version TEXT NOT NULL, object_sha TEXT NOT NULL, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            ''')
            yield db
            db.commit()
        finally:
            db.close()

    def add(self, db, sha, record, *, audit):
        if record.get('instance') != self.instance or record.get('format') != 'admitted-recipe-v1':
            raise ValueError('Invalid recipe scope')
        key = template_key(record)
        profile = record.get('version_candidate') or {}
        db.execute('INSERT OR IGNORE INTO templates VALUES(?,?,?,?,?)',
                   (key, sha, exact_key(record['resources']), len(record['resources']), int(bool(profile.get('eligible')))))
        fields = {name for r in profile.get('resources', []) for name in r.get('shape', {}).get('fields', [])}
        db.executemany('INSERT OR IGNORE INTO fields VALUES(?,?)', ((key, name) for name in fields))
        if audit:
            db.execute('INSERT INTO audits(id,template_id,registry_version,object_sha) VALUES(?,?,?,?)',
                       (uuid4().hex, key, record['version'], sha))
        return key

    def bootstrap(self, cancelled=lambda: None):
        with self.connect() as db:
            if db.execute("SELECT value FROM metadata WHERE key='legacy_indexed'").fetchone():
                return
            # Stream the one-time legacy migration; no global object-count cutoff.
            for path in self.store.root.iterdir():
                cancelled()
                if path.name.startswith('.pending-'):
                    continue
                self.add(db, path.name, json.loads(self.store.get(path.name)), audit=False)
            db.execute("INSERT INTO metadata VALUES('legacy_indexed','1')")

    def promote(self, record):
        self.bootstrap()
        key = template_key(record)
        with self.connect() as db:
            row = db.execute('SELECT object_sha FROM templates WHERE id=?', (key,)).fetchone()
            # Retain the already-verified template, with its original immutable receipts.
            sha = row['object_sha'] if row else self.store.put(json.dumps(record, sort_keys=True, ensure_ascii=False).encode())
            self.add(db, sha, record, audit=True)
        return sha

    def shortlist(self, *, files=None, fields=None, count=None, cancelled=lambda: None, limit=128):
        self.bootstrap(cancelled)
        with self.connect() as db:
            if files is not None:
                rows = db.execute('SELECT object_sha FROM templates WHERE exact_key=? ORDER BY id LIMIT ?',
                                  (exact_key(files), limit + 1)).fetchall()
            else:
                names = sorted(set(fields or []))
                if not names:
                    return [], False
                if len(names) > 2048:
                    raise ValueError('Version field search exceeds the bounded parser budget')
                # Shared fields only shortlist; official identity and every semantic
                # difference are still checked by the caller, never inferred here.
                placeholders = ','.join('?' for _ in names)
                rows = db.execute(f'''SELECT t.object_sha,count(*) AS overlap FROM templates t JOIN fields f ON f.template_id=t.id
                    WHERE t.version_eligible=1 AND t.resource_count=? AND f.field IN ({placeholders})
                    GROUP BY t.id ORDER BY overlap DESC,t.id LIMIT ?''', (count, *names, limit + 1)).fetchall()
        return [r['object_sha'] for r in rows[:limit]], len(rows) > limit
