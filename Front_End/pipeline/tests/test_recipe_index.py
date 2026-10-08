import copy
import json
from test_source_knowledge import cache_fixture, file
from arsia_pipeline import adapter_reuse as reuse


def test_one_template_many_independent_run_audits(tmp_path, monkeypatch):
    cache, session, original, _ = cache_fixture(tmp_path, monkeypatch)
    first = cache.match([original])[1]['recipe_sha256']
    for n in range(85):
        session.registered = {'adapter_version_id': f'run-version-{n}'}
        assert cache.remember(session) == first
    with cache.index.connect() as db:
        assert db.execute('SELECT count(*) FROM templates').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM audits').fetchone()[0] == 86
    assert len(list(cache.store.root.iterdir())) == 1
    renamed = file(tmp_path/'renamed.csv', ident='renamed')
    assert cache.match([renamed])[0]['contract']['resources'][0]['file_id'] == 'renamed'


def test_over_64_unrelated_templates_do_not_disable_exact_or_version_shortlist(tmp_path, monkeypatch):
    cache, _, original, _ = cache_fixture(tmp_path, monkeypatch)
    sha = cache.match([original])[1]['recipe_sha256']
    record = json.loads(cache.store.get(sha))
    target = copy.deepcopy(record)
    target['version_candidate'] = {'eligible': True, 'resources': [{'role':'crash','shape':{'fields':['ID','DATE']}}]}
    target_sha = cache.index.promote(target)
    for n in range(90):
        item = copy.deepcopy(target)
        item['contract']['source']['source_id'] = f'unrelated_{n}'
        item['resources'][0]['sha256'] = f'{n:064x}'
        item['version_candidate']['resources'][0]['shape']['fields'] = [f'OTHER_{n}']
        cache.index.promote(item)
    reads = []
    get = cache.store.get
    monkeypatch.setattr(cache.store, 'get', lambda sha: (reads.append(sha),get(sha))[1])
    assert cache.match([original])[0] is not None
    assert len(reads) == 2
    assert cache.index.shortlist(fields=['DATE','ID'],count=1) == ([target_sha],False)
    assert cache.index.shortlist(fields=['UNKNOWN'],count=1) == ([],False)
