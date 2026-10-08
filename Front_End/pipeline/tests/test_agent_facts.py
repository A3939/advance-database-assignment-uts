import hashlib
import json

import pytest

from arsia_pipeline.agent_facts import encoded, project, select_pointer, sha, snapshot_views


def test_small_result_and_exact_quote_unchanged():
    value = {'status': 'needs_input', 'quote': 'LONGITUDE uses WGS84.', 'questions': ['Exact CRS?']}
    assert project(value) == value


def test_large_projection_has_explicit_omissions_and_retrievable_values():
    value = {'status': 'needs_evidence', 'details': {'blockers': [
        {'code': 'CRS_CONFLICT', 'field': 'x', 'quote': 'Do not truncate this statement. '*600}]},
        'columns': [{'field': f'field_{i}', 'values': list(range(100))} for i in range(250)]}
    view = project(value)
    assert len(encoded(view)) <= 6144 and view['compact']
    assert view['status'] == 'needs_evidence' and view['omitted_count'] > 0
    assert 'CRS_CONFLICT' in json.dumps(view)
    assert select_pointer(value, '/details/blockers/0/quote') == value['details']['blockers'][0]['quote']
    assert 'Do not truncate' not in json.dumps(view)  # Entire long quote is omitted, not shortened.
    assert len(encoded(value)) > 10*len(encoded(view))


def test_unicode_byte_limit_and_extreme_keys_do_not_overflow():
    for value in [{'x': '证据'*50000}, {'长字段'*2000: ['原值'*10000]}, ['文档'*1000 for _ in range(100)]]:
        assert len(encoded(project(value, max_bytes=2048))) <= 2048


def test_pointer_preserves_special_keys_null_and_array_order():
    value = {'x/y': {'~field': [{'a.b': None}, '001', '1']}, '': 'empty-key'}
    assert select_pointer(value, '/x~1y/~0field/0/a.b') is None
    assert select_pointer(value, '/x~1y/~0field/1') == '001'
    assert select_pointer(value, '/') == 'empty-key'
    assert select_pointer(value, '') == value


@pytest.mark.parametrize('pointer', ['../other', '/missing', '/a/-1', '/a/01', '/a/-', '/a/9', '/~2', '/~', 42, '/'*66])
def test_invalid_selector_never_falls_back_to_whole_value(pointer):
    with pytest.raises(ValueError):
        select_pointer({'a': [1,2]}, pointer)


def test_snapshot_rebuilt_from_durable_steps_and_points_to_exact_hash():
    steps = [{'id': i, 'name': 'profile_dataset' if i%2 else 'read_document', 'status': 'succeeded',
              'result': {'file_id': 'f', 'row_count': i, 'text': 'Evidence '*5000}} for i in range(1, 31)]
    facts, index = snapshot_views(steps)
    assert len(encoded(facts)) <= 24576
    assert len(index['results']) == len(steps) and len(facts['latest_by_tool']) == 2
    assert {r['step_id'] for r in facts['latest_by_tool']} == {29,30}
    for ref, step in zip(index['results'], steps, strict=True):
        assert ref['content_hash'] == hashlib.sha256(encoded(step['result'])).hexdigest()
        assert ref['retrieve']['arguments']['step_id'] == step['id']
    assert snapshot_views(steps) == (facts,index)
    assert sha(steps[-1]['result']) == index['results'][-1]['content_hash']
