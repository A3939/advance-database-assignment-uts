"""Real PostgreSQL selection order, not an SQL-string assertion."""
from datetime import datetime, timezone

from psycopg.types.json import Jsonb
import pytest

from test_backend import isolated_database
from arsia_pipeline import registry, store


def test_jurisdiction_selection_precedes_limit_and_stable_cursor():
    same_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    with store.connect() as conn:
        for i in range(85):
            state = 'ACT' if i < 35 else 'NSW'
            sid = f'page-source-{i:03d}'
            version = f'page-version-{i:03d}'
            conn.execute('INSERT INTO source_versions(id,source_id,contract,contract_sha256,admission) VALUES(%s,%s,%s,%s,%s)',
                         (version, sid, Jsonb({'source': {'jurisdiction': [state]}}), str(i), Jsonb({})))
            conn.execute('''INSERT INTO adapter_versions(id,source_version_id,source_id,code_sha256,code_path,dependency_version,structure_signature,verification,created_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (f'adapter-page-{i:03d}', version, sid, str(i), 'not-executed', Jsonb({}), Jsonb([]), Jsonb({}), same_time))
    first = registry.search_page(jurisdiction=' act ', limit=30)
    assert len(first['adapters']) == 30 and first['has_more']
    assert all(r['contract']['source']['jurisdiction'] == ['ACT'] for r in first['adapters'])
    second = registry.search_page(jurisdiction='ACT', limit=30, cursor=first['next_cursor'])
    assert len(second['adapters']) == 5 and not second['has_more'] and second['next_cursor'] is None
    ids = [r['id'] for r in first['adapters']+second['adapters']]
    assert len(ids) == len(set(ids)) == 35 and ids == sorted(ids, reverse=True)
    assert registry.search_page(jurisdiction='NT')['adapters'] == []
    with pytest.raises(ValueError, match='cursor'):
        registry.search_page(jurisdiction='NSW', cursor=first['next_cursor'])
