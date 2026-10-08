"""Finite many-to-one lookup execution, without source/admission authority.

Parent rows are indexed in full, including unused keys and later partitions.
Each request returns at most one match and exact physical lineage. The caller
must separately ground field meaning, classify every uploaded table and replay
the resulting canonical projection. No arbitrary Python expression is accepted.
"""
from __future__ import annotations

import hashlib
import copy
import json
import math
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .errors import UnsupportedCapability, ValidationFailure
from .intakereaders import detect_tables, iter_table
from .table_plan import physical_resources, prepare_union

VERSION = 'unique-lookup-plan-v1'
MAX_ROW_BYTES = 1024 * 1024


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _sha(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _fail(code, message, **metrics):
    raise ValidationFailure(message, [{'code': code, 'status': 'block', 'message': message, 'metrics': metrics}])


def _fields(value, name, limit=64):
    if (not isinstance(value, list) or not 1 <= len(value) <= limit
            or any(not isinstance(field, str) or not field for field in value)
            or len(set(value)) != len(value)):
        _fail('LOOKUP_PLAN_INVALID', f'{name} must be a bounded, ordered list of unique field names.')
    return list(value)


def _key(row, fields, *, allow_blank=False):
    if not isinstance(row, dict) or any(field not in row for field in fields):
        _fail('LOOKUP_KEY_FIELD_ABSENT', 'A declared lookup key field is absent from the source row.')
    values = [row[field] for field in fields]
    if any(not (value is None or type(value) in (str, int, float))
           or type(value) is float and not math.isfinite(value) for value in values):
        _fail('LOOKUP_KEY_INVALID', 'Lookup keys must contain finite scalar source identifiers, never arrays, objects or booleans.')
    blank = [value is None or isinstance(value, str) and not value.strip() for value in values]
    if all(blank) and allow_blank:
        return None
    if any(blank):
        _fail('LOOKUP_KEY_INCOMPLETE', 'A lookup requires a complete key; optional association permits only an entirely blank key.')
    # No numeric coercion, whitespace stripping, Unicode normalization or
    # synthetic key is permitted. Composite order remains significant.
    return _json(values)


def _verify_input(file):
    path = Path(file['path'])
    if path.is_symlink() or not path.is_file():
        _fail('LOOKUP_INPUT_CHANGED', 'Lookup input is missing or is a symbolic link.')
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != file.get('sha256'):
        _fail('LOOKUP_INPUT_CHANGED', 'Lookup input differs from its immutable receipt.')


def prepare_lookup(resource, files, join, check_cancelled=lambda: None):
    """Validate a finite plan and pin all selected physical tables.

    `resource` is a lookup-purpose physical resource, not a canonical fact.
    `join` declares the child role, ordered foreign fields and parent columns.
    Source meaning is deliberately not inferred from equal column names.
    """
    check_cancelled()
    if (not isinstance(resource, dict)
            or set(resource) - {'role', 'purpose', 'file_id', 'table', 'key', 'partitions', 'source_url'}
            or resource.get('purpose') != 'lookup'
            or not isinstance(resource.get('role'), str)
            or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', resource['role'])):
        _fail('LOOKUP_PLAN_INVALID', 'Declare a lookup-purpose resource with an explicit role, file/table and source key.')
    if 'source_url' in resource and (not isinstance(resource['source_url'], str) or not resource['source_url']):
        _fail('LOOKUP_PLAN_INVALID', 'A lookup source_url must be a nonempty resource identifier; authority is checked by host evidence review.')
    parent_key = _fields(resource.get('key'), 'Parent key', 16)
    if (not isinstance(join, dict) or set(join) != {'child_role', 'fields', 'select', 'allow_blank', 'on_missing'}
            or not isinstance(join.get('child_role'), str)
            or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', join['child_role'])
            or join['child_role'] == resource['role']):
        _fail('LOOKUP_PLAN_INVALID', 'Declare a distinct child role and explicit lookup key, selection and missing-value policy.')
    child_key = _fields(join['fields'], 'Child key', 16)
    selected_fields = _fields(join['select'], 'Selected parent fields')
    if len(child_key) != len(parent_key) or type(join['allow_blank']) is not bool:
        _fail('LOOKUP_PLAN_INVALID', 'Lookup keys must have equal arity and allow_blank must be a boolean.')
    if join['on_missing'] not in ('error', 'preserve_unknown'):
        _fail('LOOKUP_PLAN_INVALID', 'Missing lookups must fail or preserve an explicit unknown; filtering/defaults are unsupported.')
    admitted = files if isinstance(files, dict) else {file['id']: file for file in files}
    if not isinstance(resource.get('file_id'), str) or resource['file_id'] not in admitted:
        _fail('LOOKUP_INPUT_UNADMITTED', 'Lookup parent is not an admitted input.')
    for part in physical_resources(resource):
        if part['file_id'] not in admitted:
            _fail('LOOKUP_INPUT_UNADMITTED', 'A lookup partition is not an admitted input.')
        file = admitted[part['file_id']]
        if not isinstance(file.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', file['sha256']):
            _fail('LOOKUP_INPUT_UNADMITTED', 'Lookup lineage requires an immutable SHA-256 receipt.')
        check_cancelled()
        _verify_input(file)
    if 'partitions' in resource:
        selected, union = prepare_union(resource, admitted, check_cancelled)
    else:
        hints = resource.get('table', {})
        if not isinstance(hints, dict):
            _fail('LOOKUP_PLAN_INVALID', 'Lookup table selection must be an object.')
        if any(key in hints for key in ('skip_rows', 'skipRows', 'skiprows', 'end_row', 'start_row', 'range', 'usecols', 'nrows')):
            raise UnsupportedCapability('LOOKUP_FILTER_UNSUPPORTED', 'A lookup cannot hide source rows or columns with a filter.')
        file = admitted[resource['file_id']]
        tables = detect_tables(file, hints, check_cancelled)
        selector = hints.get('sheet', hints.get('table_id'))
        matches = [table for table in tables if table['table_id'] == selector or selector is None and len(tables) == 1]
        if len(matches) != 1 or matches[0].get('empty'):
            _fail('LOOKUP_TABLE_AMBIGUOUS', 'Lookup parent must select exactly one nonempty table.')
        table = matches[0]
        for key in ('format', 'header'):
            if key in hints and hints[key] != table[key]:
                _fail('LOOKUP_SCHEMA_CONFLICT', 'Lookup parser hints conflict with the observed physical schema.')
        selected, union = [(file, table)], None
    physical = []
    for file, table in selected:
        check_cancelled()
        if not isinstance(file.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', file['sha256']):
            _fail('LOOKUP_INPUT_UNADMITTED', 'Lookup lineage requires an immutable SHA-256 receipt.')
        _verify_input(file)
        missing = sorted(set(parent_key + selected_fields) - set(table['header']))
        if missing:
            _fail('LOOKUP_FIELD_ABSENT', 'Lookup key or selected fields are absent from a physical parent table.', fields=missing)
        if table['format'] == 'xlsx':
            from .workbook_plan import validate_hint
            # prepare_union already selected each physical table; it must still
            # honor any supplied immutable workbook parser plan.
            hints = (resource.get('partitions') or [resource])[len(physical)].get('table', {})
            validate_hint(table, hints)
        physical.append({'file_sha256': file['sha256'], 'table_id': table['table_id'],
                         'format': table['format'], 'fields': table['header'], 'parser_plan': table.get('parser_plan')})
    plan = {'version': VERSION, 'operation': 'unique_lookup', 'parent_role': resource['role'],
            'child_role': join['child_role'], 'parent_key': parent_key, 'child_key': child_key,
            'select': selected_fields, 'allow_blank': join['allow_blank'], 'on_missing': join['on_missing'],
            'inputs': physical, 'union_plan': union,
            'key_policy': 'exact_finite_scalar_composite; whitespace_only_is_blank; no_coercion_or_extra_null_sentinels',
            'cardinality': 'each_child_has_zero_or_one_parent; all_parent_keys_unique_including_unused',
            'row_policy': 'all_parent_rows_indexed; no_filter_no_deduplication; child_rows_never_expanded',
            'authority': 'structural_only_requires_separate_scoped_semantic_evidence'}
    plan['plan_sha256'] = _sha(plan)
    return selected, plan


class LookupIndex:
    """Full-parent disk index shared by a future SDK and trusted replay caller.

    Keep the object task-local, use as a context manager, and call receipt()
    after processing. A failed request invalidates its final receipt; a caller
    cannot catch malformed rows and claim conservation from the surviving rows.
    """
    def __init__(self, resource, files, join, work_dir, check_cancelled=lambda: None):
        self.cancelled = check_cancelled
        self._selected, plan = prepare_lookup(resource, files, join, check_cancelled)
        self._selected = copy.deepcopy(self._selected)
        # Keep an internal snapshot; callers receive defensive copies.
        self._plan = json.loads(_json(plan))
        self._db = None
        self._failed = False
        self._closed = False
        self._metrics = {'parent_rows': 0, 'requests': 0, 'matched': 0, 'unmatched': 0,
                         'all_blank': 0, 'rejected': 0, 'join_extra_rows': 0}
        self._physical = []
        root = Path(work_dir)
        if root.is_symlink():
            _fail('LOOKUP_WORKSPACE_INVALID', 'Lookup workspace must not be a symbolic link.')
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / ('lookup-' + uuid4().hex + '.sqlite')
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        try:
            self._db = sqlite3.connect(self.path)
            self._db.execute('PRAGMA temp_store=FILE')
            self._db.execute('PRAGMA cache_size=-8192')
            self._db.execute('PRAGMA journal_mode=OFF')
            self._db.execute('CREATE TABLE parents(k TEXT PRIMARY KEY, payload TEXT NOT NULL, lineage TEXT NOT NULL, refs INTEGER NOT NULL DEFAULT 0)')
            for file, table in self._selected:
                count = 0
                rows_hash = hashlib.sha256()
                for locator, row in iter_table(file, table, self.cancelled):
                    self.cancelled()
                    key = _key(row, self._plan['parent_key'])
                    if any(field not in row for field in self._plan['select']):
                        _fail('LOOKUP_VALUE_FIELD_ABSENT', 'A selected lookup field is absent from a parent row; absent is not silently converted to null.',
                              file_sha256=file['sha256'], table_id=table['table_id'], row_locator=locator)
                    payload = _json(row)
                    if len(payload.encode()) > MAX_ROW_BYTES:
                        _fail('LOOKUP_ROW_TOO_LARGE', 'Lookup parent row exceeds the bounded representation size.')
                    lineage = {'resource_role': resource['role'], 'file_sha256': file['sha256'],
                               'table_id': table['table_id'], 'row_locator': locator,
                               'row_sha256': hashlib.sha256(payload.encode()).hexdigest()}
                    try:
                        self._db.execute('INSERT INTO parents(k,payload,lineage) VALUES(?,?,?)', (key, payload, _json(lineage)))
                    except sqlite3.IntegrityError:
                        _fail('LOOKUP_PARENT_NOT_UNIQUE', 'Lookup parent keys are not unique across the complete physical inputs; no rows were deduplicated.',
                              parent_role=resource['role'], file_sha256=file['sha256'], table_id=table['table_id'], row_locator=locator)
                    count += 1
                    self._metrics['parent_rows'] += 1
                    rows_hash.update((_json([locator, row]) + '\n').encode())
                    if count % 5000 == 0:
                        self._db.commit()
                if not count:
                    _fail('LOOKUP_PARENT_EMPTY', 'A required lookup parent table contains no records.')
                self._physical.append({'file_sha256': file['sha256'], 'table_id': table['table_id'],
                                       'rows': count, 'row_stream_sha256': rows_hash.hexdigest()})
            self._db.commit()
            self._verify_inputs()
        except BaseException:
            self._failed = True
            self.close()
            raise

    @property
    def plan(self):
        return json.loads(_json(self._plan))

    def _verify_inputs(self):
        for file, _ in self._selected:
            self.cancelled()
            _verify_input(file)

    def resolve(self, child_row):
        if self._closed or self._failed:
            _fail('LOOKUP_INDEX_UNUSABLE', 'Closed or failed lookup indexes cannot process further records.')
        self._metrics['requests'] += 1
        try:
            self.cancelled()
            key = _key(child_row, self._plan['child_key'], allow_blank=self._plan['allow_blank'])
            if key is None:
                self._metrics['all_blank'] += 1
                return {'status': 'not_associated', 'values': {field: None for field in self._plan['select']}, 'lineage': None}
            result = self._db.execute('SELECT payload,lineage FROM parents WHERE k=?', (key,)).fetchone()
            if result is None:
                self._metrics['unmatched'] += 1
                if self._plan['on_missing'] == 'error':
                    _fail('LOOKUP_UNMATCHED', 'A complete child key has no matching lookup parent; the child row was not filtered.')
                return {'status': 'unmatched', 'values': {field: None for field in self._plan['select']}, 'lineage': None}
            row = json.loads(result[0])
            self._db.execute('UPDATE parents SET refs=refs+1 WHERE k=?', (key,))
            self._metrics['matched'] += 1
            return {'status': 'matched', 'values': {field: row[field] for field in self._plan['select']},
                    'lineage': json.loads(result[1])}
        except BaseException:
            self._failed = True
            self._metrics['rejected'] += 1
            raise

    def receipt(self):
        if self._closed or self._failed:
            _fail('LOOKUP_INDEX_UNUSABLE', 'A closed or failed lookup index cannot produce a completed receipt.')
        try:
            self._verify_inputs()
        except BaseException:
            self._failed = True
            raise
        used, maximum = self._db.execute('SELECT count(*),COALESCE(max(refs),0) FROM parents WHERE refs>0').fetchone()
        self._db.commit()
        value = {'plan': self.plan, 'physical_tables': self._physical,
                 'metrics': {**self._metrics, 'used_parent_keys': used,
                             'unused_parent_keys': self._metrics['parent_rows'] - used,
                             'max_children_per_parent': maximum},
                 'complete_parent_scan': True, 'admission': False,
                 'scope': 'Recorded requests only; caller must independently prove all child rows were processed and ground semantics.'}
        value['receipt_sha256'] = _sha(value)
        return json.loads(_json(value))

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
