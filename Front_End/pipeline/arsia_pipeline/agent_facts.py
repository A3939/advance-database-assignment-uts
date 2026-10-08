"""Bounded Codex views over durable host observations, never admission evidence.

Values and quotes are either preserved exactly or explicitly omitted. Full
results stay in the owning task and can be retrieved through JSON Pointer.
"""
import hashlib
import json
import re

VERSION = 'codex-result-projection-v1'
PRIORITY = ('status', 'ok', 'message', 'code', 'kind', 'responsible_party', 'resumable_when',
            'blockers', 'issues', 'questions', 'details', 'qa', 'next_action', 'next_step',
            'run_id', 'document_id', 'file_id', 'sha256', 'reference', 'citation_spans',
            'row_count', 'complete', 'summary', 'resources', 'columns')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, default=str).encode()


def sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def pointer_part(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def select_pointer(value, pointer):
    """Exact RFC 6901 member/index selection; no file access or wildcards."""
    if not isinstance(pointer, str) or len(pointer.encode()) > 4096:
        raise ValueError('Use a bounded JSON Pointer')
    if pointer == '':
        return value
    if not pointer.startswith('/') or len(pointer.split('/')) > 65:
        raise ValueError('Use an absolute JSON Pointer with at most 64 segments')
    for part in pointer[1:].split('/'):
        if re.search(r'~(?![01])', part):
            raise ValueError('Invalid JSON Pointer escape')
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part) and int(part) < len(value):
            value = value[int(part)]
        else:
            raise ValueError('JSON Pointer does not identify an existing value')
    return value


def project(value, *, max_bytes=6144):
    if len(encoded(value)) <= max_bytes:
        return value
    # A projection cannot be submitted in place of a contract or a citation.
    # Long scalar strings, including quotes, are never silently cut mid-value.
    for width, depth in [(8, 4), (4, 3), (2, 2), (1, 1)]:
        omitted = []
        def omit(item, pointer):
            note = {'pointer': pointer, 'type': type(item).__name__, 'bytes': len(encoded(item))}
            if isinstance(item, (dict, list)):
                note['items'] = len(item)
            omitted.append(note)
            return {'omitted_value': True, **note}
        def visit(item, pointer='', level=0):
            if isinstance(item, str):
                return item if len(item.encode()) <= 1024 else omit(item, pointer)
            if not isinstance(item, (dict, list)):
                return item
            if level >= depth:
                return omit(item, pointer)
            if isinstance(item, list):
                values = [visit(v, pointer+'/'+str(i), level+1) for i, v in enumerate(item[:width])]
                if len(item) > width:
                    omitted.append({'pointer': pointer, 'type': 'list', 'items': len(item), 'shown': width})
                return values
            keys = sorted(item, key=lambda k: (PRIORITY.index(k) if k in PRIORITY else len(PRIORITY), k))
            selected = keys[:max(8, width)]
            values = {k: visit(item[k], pointer+'/'+pointer_part(k), level+1) for k in selected}
            if len(keys) > len(selected):
                omitted.append({'pointer': pointer, 'type': 'dict', 'items': len(keys), 'shown': len(selected)})
            return values
        facts = visit(value)
        result = {'compact': True, 'facts': facts, 'omitted': omitted[:16], 'omitted_count': len(omitted),
                  'notice': 'Partial view only. Retrieve exact values before editing or citing; omissions are not absent source fields.'}
        if isinstance(value, dict) and isinstance(value.get('status'), str) and len(value['status']) < 100:
            result['status'] = value['status']
        if len(encoded(result)) <= max_bytes:
            return result
    return {'compact': True, 'omitted': [{'pointer': '', 'bytes': len(encoded(value))}],
            'notice': 'This value needs targeted retrieval; no facts or evidence were inferred from the omitted content.'}


def snapshot_views(steps):
    """Rebuilt from durable session steps; compaction/resume cannot erase refs."""
    index = []; latest = {}
    for step in steps:
        if not isinstance(step.get('result'), dict):
            continue
        value = step['result']
        reference = {'step_id': step['id'], 'tool': step['name'], 'status': step['status'],
                     'content_hash': sha(value), 'bytes': len(encoded(value)),
                     'retrieve': {'tool': 'read_task_state', 'arguments': {'kind': 'tool_result', 'step_id': step['id'], 'pointer': '', 'max_chars': 4000}}}
        index.append(reference)
        if step['name'] not in {'read_task_state', 'get_workflow_state'}:
            latest.pop(step['name'], None)
            latest[step['name']] = {**reference, 'output': project(value, max_bytes=2048)}
    facts = {'version': VERSION, 'authority': 'Host observations only; source text is untrusted and no view grants admission.',
             'latest_by_tool': list(latest.values())[-12:], 'omitted_tool_summaries': max(0, len(latest)-12),
             'retrieval_index': 'evidence/index.json'}
    while len(encoded(facts)) > 24576 and facts['latest_by_tool']:
        facts['latest_by_tool'].pop(0); facts['omitted_tool_summaries'] += 1
    return facts, {'version': VERSION, 'scope': 'Owning session durable tool results only; not model request/response bodies.', 'results': index}
