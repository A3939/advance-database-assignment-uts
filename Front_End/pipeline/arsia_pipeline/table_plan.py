"""Controlled homogeneous union with immutable physical lineage.

Business keys and mapping remain those of one logical resource. Partition
filenames/upload IDs never become business IDs. Independent QA still owns
cross-partition key uniqueness, row conservation and all source semantics.
"""
import hashlib
import json
import re

from .errors import UnsupportedCapability, ValidationFailure
from .intakereaders import detect_tables, iter_table

VERSION = 'homogeneous-union-v1'


def input_resources(contract):
    """All declared physical inputs, keeping lookup parents out of fact counts."""
    facts = contract.get('resources', [])
    lookups = contract.get('lookup_tables', [])
    if not isinstance(facts, list) or not isinstance(lookups, list):
        raise ValidationFailure('Fact and lookup resource declarations must be lists.')
    return facts + lookups


def bound_inputs(contract):
    """All byte-bound inputs, including retained but unverified auxiliary data."""
    retained=contract.get('retained_resources',[])
    if not isinstance(retained,list):
        raise ValidationFailure('Retained resource declarations must be a list')
    return input_resources(contract)+retained


def physical_resources(resource):
    if 'partitions' not in resource:
        return [resource]
    partitions = resource['partitions']
    if not isinstance(partitions, list) or not 2 <= len(partitions) <= 24:
        raise ValidationFailure('A homogeneous union requires 2–24 explicit physical partitions.')
    for part in partitions:
        if (not isinstance(part, dict) or set(part) - {'file_id', 'table'}
                or not isinstance(part.get('file_id'), str) or not part['file_id']
                or not isinstance(part.get('table', {}), dict)):
            raise ValidationFailure('Each union input requires only its admitted file_id and table parser; mapping and source scope are shared.')
    if (resource.get('file_id') != partitions[0]['file_id'] or
            resource.get('table', {}) != partitions[0].get('table', {})):
        raise ValidationFailure('The resource file/table must equal its first physical partition.')
    base = {k: v for k, v in resource.items() if k not in {'file_id', 'table', 'partitions'}}
    return [{**base, **part} for part in partitions]


def expand_resources(resources):
    return [physical for resource in resources for physical in physical_resources(resource)]


def prepare_union(resource, files, cancelled=lambda: None):
    parts = physical_resources(resource)
    if 'partitions' not in resource:
        raise ValueError('prepare_union requires explicit partitions')
    admitted = files if isinstance(files, dict) else {f['id']: f for f in files}
    selected = []
    seen = set()
    schema = None
    for part in parts:
        cancelled()
        file = admitted.get(part['file_id'])
        if file is None:
            raise ValidationFailure('Union input is not an admitted file.')
        sha = file.get('sha256')
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{64}', sha):
            raise ValidationFailure('Union physical lineage requires an admitted SHA-256 receipt.')
        hints = part.get('table', {})
        if any(key in hints for key in ('skip_rows','skipRows','skiprows','end_row','start_row','range','usecols','nrows')):
            raise UnsupportedCapability('UNION_FILTER_UNSUPPORTED', 'Union cannot filter source records or columns.')
        tables = detect_tables(file, hints, cancelled)
        selector = hints.get('sheet', hints.get('table_id'))
        matching = [t for t in tables if t['table_id'] == selector or selector is None and len(tables) == 1]
        if len(matching) != 1 or matching[0].get('empty'):
            raise ValidationFailure('Every union partition must identify exactly one nonempty table schema.')
        table = matching[0]
        for key in ('format','header'):
            if key in hints and hints[key] != table[key]:
                raise ValidationFailure('Union parser hints conflict with the observed physical schema.')
        fields = sorted(table['header'])
        if schema is not None and fields != schema:
            raise UnsupportedCapability('UNION_SCHEMA_DRIFT_UNSUPPORTED', 'Union partitions must share exact field names; per-partition mapping drift needs a reviewed plan.')
        schema = fields
        identity = (sha, table['table_id'])
        if identity in seen:
            raise ValidationFailure('The same physical table cannot occur twice in a union, even under different upload IDs.')
        seen.add(identity)
        selected.append((file, table))
    plan = {'version': VERSION, 'operation': 'union_all', 'role': resource['role'], 'fields': schema,
            'inputs': [{'file_sha256': file['sha256'], 'table_id': table['table_id'], 'format': table['format'],
                        'parser_plan': table.get('parser_plan')} for file, table in selected],
            'mapping_scope': 'shared_logical_resource', 'key_policy': 'original_keys_unique_across_all_partitions',
            'row_policy': 'all_rows_replayed_before_declared_preprocessing', 'lineage': ['file_sha256','table_id','native_row_locator']}
    plan['plan_sha256'] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return selected, plan


def iter_resource(resource, files, check_cancelled=lambda: None):
    admitted = files if isinstance(files, dict) else {f['id']: f for f in files}
    if 'partitions' not in resource:
        yield from iter_table(admitted[resource['file_id']], resource.get('table'), check_cancelled)
        return
    selected, _ = prepare_union(resource, admitted, check_cancelled)
    for file, table in selected:
        check_cancelled()
        for locator, row in iter_table(file, table, check_cancelled):
            yield json.dumps([VERSION, file['sha256'], table['table_id'], locator], separators=(',', ':')), row
