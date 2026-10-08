"""Limited task relevance review; metadata inspection never grants data admission.

Bindings name actual table fields. The host checks sampled values/relationships;
filenames, domain names, source prose and a model's relevance assertion cannot
grant execution. Ambiguous/unknown formats retain a bounded review path.
"""
from contextlib import closing
from datetime import datetime
import hashlib
import itertools
import json
import re
import time
from pathlib import Path

from .errors import BudgetExhausted, NeedsInput

VERSION = 'task-authority-v1'


class TaskIntegrityError(RuntimeError):
    code = 'TASK_INPUT_INTEGRITY'
    kind = 'system_configuration'

METADATA_TOOLS = {'inspect_task_scope', 'inspect_bundle', 'inspect_capabilities', 'read_task_state',
                  'read_document', 'get_adapter_contract', 'get_workflow_state',
                  'read_source_knowledge', 'read_source_evidence', 'request_missing_information',
                  'request_engineering_repair'}
DISCOVERY_TOOLS = {'discover_source_docs', 'fetch_public_source', 'compare_source_metadata'}
PURPOSES = {'crash_intake', 'road_safety_observations', 'weather_comparison', 'population_denominator', 'geographic_linkage', 'traffic_units', 'casualties'}

# Additional ceilings for the new opt-in policy; these never increase the
# selected model/tool/compute/storage policy. Download bytes include failures
# and repeated downloads even when the content-addressed archive deduplicates.
METADATA_BYTES = 6 * 1024**2
DOWNLOAD_BYTES = 256 * 1024**2
TASK_STORAGE_BYTES = 512 * 1024**2


def resource_usage(session):
    return session.runtime_state.setdefault('bounded_resources', {
        'download_bytes': 0, 'metadata_download_bytes': 0, 'storage_peak_bytes': 0,
        'limits': {'metadata_download_bytes': METADATA_BYTES,
                   'download_bytes': DOWNLOAD_BYTES, 'task_storage_bytes': TASK_STORAGE_BYTES}})


def request_limits(session, size, seconds):
    usage = resource_usage(session)
    remaining = DOWNLOAD_BYTES - usage['download_bytes']
    if state(session)['status'] != 'scoped_for_investigation':
        remaining = min(remaining, METADATA_BYTES - usage['metadata_download_bytes'])
        size, seconds = min(size, 2 * 1024**2), min(seconds, 15)
    if remaining <= 0:
        raise BudgetExhausted('Cumulative public-evidence byte budget exhausted.', {'limit': 'download_bytes', 'usage': usage})
    return min(size, remaining), seconds


def charge_download(session, count):
    usage = resource_usage(session)
    usage['download_bytes'] += count
    if state(session)['status'] != 'scoped_for_investigation':
        usage['metadata_download_bytes'] += count
    if usage['download_bytes'] > DOWNLOAD_BYTES or usage['metadata_download_bytes'] > METADATA_BYTES:
        raise BudgetExhausted('Cumulative public-evidence byte budget exhausted.', {'limit': 'download_bytes', 'usage': usage})


def check_storage(session, *, force=False):
    now = time.monotonic()
    if not force and now - getattr(session, '_last_storage_check', 0) < 1:
        return
    session._last_storage_check = now
    from .codex_resources import storage_bytes
    usage = resource_usage(session)
    try:
        # All attempts of this job, not just the current script/run directory.
        size = storage_bytes([Path(session.job['work_dir']).parent], TASK_STORAGE_BYTES)
    except ValueError as exc:
        raise BudgetExhausted('Task evidence storage or file-count limit exhausted; existing evidence is retained.',
                              {'limit': str(exc), 'usage': usage}) from exc
    usage['storage_peak_bytes'] = max(size, usage['storage_peak_bytes'])


def state(session):
    return session.runtime_state.setdefault('task_authority', {
        'version': VERSION, 'objective': 'Australian road safety intake, QA and directly supporting analysis',
        'files': {}, 'review_actions': 0, 'status': 'metadata_only'})


def verified_file(session, file_id):
    files = [f for f in session.files if f['id'] == file_id]
    if len(files) != 1:
        raise ValueError('Unknown task file_id; paths are not accepted')
    file = files[0]
    path = Path(file['path'])
    if path.is_symlink() or not path.is_file() or path.stat().st_size != file['size']:
        raise TaskIntegrityError('Task input integrity failure')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != file['sha256']:
            raise TaskIntegrityError('Task input hash changed')
    return file


def sample(session, file, table_id=None, *, limit=64):
    # Trusted parser subprocess has its own CPU/memory/wall limit; sample rows
    # stay on the host, only fields and aggregate checks are returned to Agent.
    from .intakereaders import detect_tables, iter_table
    tables = detect_tables(file, check_cancelled=session.cancel)
    selected = [t for t in tables if table_id is None or t['table_id'] == table_id]
    if len(selected) != 1:
        raise ValueError('Select one actual table from inspect_bundle')
    table = selected[0]
    with closing(iter_table(file, table, session.cancel)) as rows:
        records = [row for _, row in itertools.islice(rows, limit)]
    return table, records


def date_value(value):
    text = str(value)
    if re.fullmatch(r'(19|20)\d{2}', text):
        return True
    try:
        datetime.fromisoformat(text.replace('Z', '+00:00'))
        return True
    except ValueError:
        pass
    for fmt in ('%d/%m/%Y', '%m/%d/%Y', '%d/%m/%Y %H:%M:%S', '%d-%b-%Y'):
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            pass
    return False


def review(session, args):
    authority = state(session)
    file = verified_file(session, args['file_id'])
    table, rows = sample(session, file, args.get('table_id'))
    fields = list(table.get('columns', []))
    # Some readers call their actual column list headers.
    if not fields and rows:
        fields = list(rows[0])
    bindings = args.get('bindings') or {}
    if not isinstance(bindings, dict) or set(bindings) - {'key', 'date', 'outcome', 'measure', 'join_key'}:
        raise ValueError('Bind only key/date/outcome/measure/join_key to actual fields')
    if any(not isinstance(v, str) or v not in fields for v in bindings.values()):
        raise ValueError('Every scope binding must identify an actual table field')
    purpose = args.get('purpose')
    if purpose not in PURPOSES:
        raise ValueError('Purpose is outside ARSIA task authority')
    result = {'status': 'metadata_only', 'file_id': file['id'], 'sha256': file['sha256'],
              'table_id': table['table_id'], 'fields': fields, 'sampled_rows': len(rows),
              'purpose': purpose, 'bindings': bindings, 'official_identity_verified': False,
              'admission': False}
    primary = purpose in {'crash_intake', 'road_safety_observations'}
    needed = {'key', 'date', 'outcome'} if primary else {'join_key', 'measure'}
    if not needed <= set(bindings) or not rows:
        result['next_action'] = 'Propose field bindings from this real sample; unsupported readers require engineering review.'
        return result
    if primary:
        keys = [row.get(bindings['key']) for row in rows]
        dates = [row.get(bindings['date']) for row in rows]
        outcomes = [row.get(bindings['outcome']) for row in rows]
        # Paired structural + value evidence, not filenames/road keywords alone.
        key_ok = all(isinstance(v, (str, int)) and str(v).strip() for v in keys)
        date_ok = sum(date_value(v) for v in dates) >= max(1, len(rows)*.8)
        outcome_ok = all(isinstance(v, (str, int)) and 0 < len(str(v)) <= 160 for v in outcomes)
        road_fields = [f for f in fields if re.search(r'crash|accident|collision|csef|severity|injur|fatal|killed|road.?user', f, re.I)]
        recognized_outcomes = all(re.fullmatch(r'(?:fatal|fatal crash|injury|serious injury|minor injury|property damage only|non.?injury)', str(v), re.I) for v in outcomes)
        result['checks'] = {'key_present': key_ok, 'dates_plausible': date_ok,
                            'outcome_values_bounded': outcome_ok, 'domain_fields': road_fields[:12]}
        accepted = key_ok and date_ok and outcome_ok and (bool(road_fields) or recognized_outcomes)
    else:
        parent = authority['files'].get(args.get('parent_file_id'))
        if not parent or parent['purpose'] not in {'crash_intake', 'road_safety_observations'}:
            raise ValueError('Auxiliary data requires an already scoped primary road-safety resource')
        pf = verified_file(session, args['parent_file_id'])
        _, parents = sample(session, pf, parent['table_id'], limit=10000)
        parent_field = args.get('parent_field')
        if not isinstance(parent_field, str) or not all(parent_field in row for row in parents):
            raise ValueError('Auxiliary relationship needs an actual parent field')
        values = {json.dumps(row.get(parent_field), sort_keys=True) for row in parents if row.get(parent_field) is not None}
        matched = sum(json.dumps(row.get(bindings['join_key']), sort_keys=True) in values for row in rows)
        nonempty = sum(row.get(bindings['measure']) not in (None, '') for row in rows)
        accepted = matched >= min(3, len(rows)) and nonempty > 0
        result['checks'] = {'sample_matching_rows': matched, 'sample_measure_rows': nonempty,
                            'parent_file_id': pf['id'], 'parent_sha256': pf['sha256'], 'parent_field': parent_field,
                            'parent_rows_checked':len(parents), 'not_a_full_relation_proof':True}
    if accepted:
        result['status'] = 'scoped_for_investigation'
        result['limitations'] = ['Sample relevance only; not source or semantic authentication.',
                                'Auxiliary relations and every canonical row still require full independent QA.']
        authority['files'][file['id']] = result
        authority['status'] = 'scoped_for_investigation'
    else:
        result['next_action'] = 'Scope is not established. Supply a concrete road-safety field/relationship or stop; no Python execution is authorized.'
    return result


def require_files(session, file_ids):
    if not isinstance(file_ids, list) or not 1 <= len(file_ids) <= 12 or len(set(file_ids)) != len(file_ids):
        raise ValueError('Select 1–12 unique task file IDs')
    authority = state(session)
    result = []
    for ident in file_ids:
        file = verified_file(session, ident)
        scoped = authority['files'].get(ident)
        if not scoped or scoped['sha256'] != file['sha256']:
            raise ValueError('This resource has no host-checked task scope; inspect_task_scope first')
        result.append(file)
    return result


def authorize(session, name, args):
    authority = state(session)
    if name in METADATA_TOOLS:
        return
    if authority['status'] != 'scoped_for_investigation':
        # Unknown sources can obtain bounded semantic metadata before a verdict.
        if name in DISCOVERY_TOOLS and authority['review_actions'] < 3:
            authority['review_actions'] += 1
            return
        exc = NeedsInput('Task relevance has not been established by bounded metadata/sample review. '
                         'No execution or extended research was authorized.', [], {'task_scope': authority})
        exc.code = 'scope_review_pending'
        raise exc
    if name in {'profile_dataset', 'inspect_relations'}:
        ids = [value for key, value in args.items() if key.endswith('file_id')]
        require_files(session, ids)
    if name in {'set_source_contract', 'preflight_contract'}:
        candidate = args.get('contract', session.contract)
        if candidate:
            from .table_plan import bound_inputs
            ids = list(dict.fromkeys(r['file_id'] for r in bound_inputs(candidate)))
            require_files(session, ids)
