"""Explicit ACT acceptance in an owned PostgreSQL container; no model calls.

Uses the existing API, AgentSession, sandbox, QA, registry and publication. The
source oracle uses csv/datetime/Decimal independently of canonical.project.
Never resumes old jobs, switches a website release or mutates live config.
All evidence, the stopped database and volume are retained, including failure.
"""
import argparse
from collections import Counter
import copy
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import time
from uuid import uuid4


def save(path, value):
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, default=str)


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def oracle(source, candidate):
    """Full independent per-key date/category/raw/coordinate comparison."""
    expected = {}
    groups = Counter()
    with source.open(encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            key = row['CRASH_ID']
            assert key not in expected, 'Duplicate source crash key'
            expected[key] = row
            groups[(datetime.strptime(row['CRASH_DATE'], '%d/%m/%Y').year, row['CRASH_SEVERITY'])] += 1
    seen = set()
    maximum_rounding_delta = Decimal(0)
    halfway_cases = 0
    categories = {'Fatal': 'fatal', 'Injury': 'injury', 'Property damage only': 'property_damage_only'}
    with candidate.open() as handle:
        for line in handle:
            row = json.loads(line)
            key, = json.loads(row['record_id'])
            assert key not in seen, 'Duplicate candidate crash key'
            seen.add(key)
            original = expected[key]
            date = datetime.strptime(original['CRASH_DATE'], '%d/%m/%Y')
            assert row['year'] == date.year and row['month'] == date.month
            assert row['occurrence_date'] == date.date().isoformat()
            assert row['raw_severity'] == original['CRASH_SEVERITY']
            assert row['severity'] == categories[original['CRASH_SEVERITY']]
            assert row['is_fatal_crash'] == (original['CRASH_SEVERITY'] == 'Fatal')
            assert row['fatalities'] is None and row['casualties'] is None
            assert row['extensions'] == original, 'Raw field loss/change'
            for actual, field in zip(row['coordinates'], ('LONGITUDE', 'LATITUDE'), strict=True):
                # The product stores 8 decimal places. At an exact halfway
                # input either nearest value is defensible after binary-float
                # conversion; independently bound error to half one decimal
                # step rather than reusing canonical's float rounding code.
                value = Decimal(str(actual))
                delta = abs(value - Decimal(original[field]))
                assert value == value.quantize(Decimal('.00000001'))
                assert delta <= Decimal('.000000005'), 'Coordinate exceeds declared 8-decimal rounding bound'
                maximum_rounding_delta = max(maximum_rounding_delta, delta)
                halfway_cases += int(delta == Decimal('.000000005'))
    assert seen == expected.keys()
    return {'rows': len(seen), 'fatal_crashes': sum(n for (year, severity), n in groups.items() if severity == 'Fatal'),
            'year_severity': [{'year': y, 'severity': s, 'count': n} for (y, s), n in sorted(groups.items())],
            'raw_fields_preserved': True, 'person_counts_unknown': True,
            'max_canonical_rounding_delta_degrees': str(maximum_rounding_delta), 'halfway_coordinate_cases': halfway_cases,
            'scope': 'Full per-key comparison; does not establish survey accuracy or official all-row certification.'}


def verify_query(value, independent):
    """Compare released query aggregates with the independent CSV oracle."""
    assert value['summary'] == {'crash_count': independent['rows'], 'fatal_crash_count': independent['fatal_crashes'],
                                'fatalities': None, 'casualties': None}
    expected_years = {}
    severity = Counter()
    for row in independent['year_severity']:
        year = expected_years.setdefault(row['year'], {'year': row['year'], 'crash_count': 0,
            'fatal_crash_count': 0, 'fatalities': None, 'casualties': None})
        year['crash_count'] += row['count']
        if year['fatal_crash_count'] is not None:year['fatal_crash_count'] += row['count'] if row['severity'] == 'Fatal' else 0
        severity[row['severity']] += row['count']
        if row['severity']=='Not known':year['fatal_crash_count']=None
    assert value['yearly'] == [expected_years[y] for y in sorted(expected_years)]
    assert {row['label']: row['count'] for row in value['severity']} == dict(severity)
    assert value['geography']['status'] == 'available'
    return {'summary_matches': True, 'yearly_matches': True, 'severity_matches': True,
            'geography_available': True, 'person_counts_remain_unknown': True}


def run(args):
    output = args.output.resolve()
    from managed_acceptance import child_config
    cfg = child_config(output)
    from arsia_pipeline import config, isolated_executor
    from psycopg.conninfo import conninfo_to_dict
    password = conninfo_to_dict(cfg['dsn'])['password']
    start = time.monotonic()
    timings = []
    oracle_fn = oracle
    if getattr(args,'dataset','act') == 'tas':
        from acceptance_oracles import tas
        oracle_fn = tas

    def measured(name, fn):
        at = datetime.now(timezone.utc).isoformat()
        tick = time.monotonic()
        try:
            result = fn()
        except BaseException:
            timings.append({'stage': name, 'at': at, 'seconds': time.monotonic() - tick, 'status': 'failed'})
            raise
        timings.append({'stage': name, 'at': at, 'seconds': time.monotonic() - tick, 'status': 'passed'})
        print(name, 'passed', round(timings[-1]['seconds'], 2), flush=True)
        return result

    try:
        import psycopg
        from arsia_pipeline import api, store, worker, agent
        from arsia_pipeline.adapter_reuse import ADAPTER, controlled
        from arsia_pipeline.codex_runtime import CodexRuntime
        from fastapi.testclient import TestClient
        store.initialize(cfg)

        def forbidden(*a, **kw):
            raise AssertionError('Deterministic acceptance must not call models')
        agent.gateway = forbidden
        CodexRuntime.run = forbidden
        contract = json.loads((args.proof / 'contract.json').read_text())
        files = json.loads((args.proof / 'files.json').read_text())
        original = next(f for f in files if f['id'] == contract['resources'][0]['file_id'])
        source = Path(original['path'])
        assert digest(source) == original['sha256']
        docs = {}
        folder = config.ROOT / 'evidence'
        (folder / 'sha256').mkdir(parents=True)
        for doc in contract.pop('documents'):
            doc = copy.deepcopy(doc)
            receipt = Path(doc['receipt_path'])
            raw = receipt.parent / 'sha256' / doc['sha256']
            assert digest(raw) == doc['sha256']
            target = folder / 'sha256' / doc['sha256']
            shutil.copyfile(raw, target)
            doc['content_path'] = str(target)
            for field, suffix in [('text_path', '.txt'), ('receipt_path', '.receipt.json')]:
                if doc.get(field):
                    target = folder / (doc['document_id'] + suffix)
                    shutil.copyfile(doc[field], target)
                    doc[field] = str(target)
            docs[doc['document_id']] = doc
        client = TestClient(api.app)

        def new_job(filename):
            response = client.post('/jobs', json={'label': 'ACT isolated full acceptance'})
            response.raise_for_status()
            ident = response.json()['id']
            with source.open('rb') as stream:
                client.put('/jobs/' + ident + '/files', params={'filename': filename}, content=stream.read()).raise_for_status()
            client.post('/jobs/' + ident + '/submit', json={}).raise_for_status()
            with store.connect() as conn:
                job = worker.claim(conn, cfg)
            assert str(job['id']) == ident
            work = job['work_dir'] / 'agent'
            work.mkdir()
            return job, work

        first, work = measured('upload_and_claim', lambda: new_job(original['name']))
        session = agent.AgentSession(first['files'], work, first['options'], lambda *a, **kw: None, lambda: None, first)
        measured('inspect', lambda: controlled(session, 'inspect_bundle', {}))
        from managed_acceptance import copy_public_reference
        references=[copy_public_reference(f,config.ROOT/'resource-receipts') for f in files
                    if f.get('role')=='public_evidence' and f.get('receipt_path')]
        session.intake.register_files(references)
        session.files=list(session.intake.files)
        contract['resources'][0]['file_id'] = session.files[0]['id']
        session.documents = docs
        measured('contract_preflight', lambda: controlled(session, 'set_source_contract', {'contract': contract}))
        controlled(session, 'write_adapter', {'code': ADAPTER, 'reason': 'Fresh full acceptance of reviewed source contract with current QA'})
        for mode in ('sample', 'full'):
            executed = measured(mode + '_execute', lambda: controlled(session, 'run_adapter', {'mode': mode}))
            measured(mode + '_QA', lambda: controlled(session, 'validate_candidate', {'run_id': executed['run_id']}))
        independent = measured('independent_full_oracle', lambda: oracle_fn(source, Path(session.validated['canonical_path'])))
        save(output / 'independent-oracle.json', independent)
        measured('register', lambda: controlled(session, 'register_adapter', {}))
        measured('prepare_publication', lambda: controlled(session, 'publish_candidate', {}))
        measured('publish', lambda: worker.publish(first, session.ready, lambda: None))
        result = store.get_job(first['id'])
        save(output / 'initial.json', agent.safe(result))
        assert result['status'] == 'succeeded'
        assert result['result']['summary']['crash_count'] == independent['rows']
        assert result['result']['summary']['fatal_crash_count'] == independent['fatal_crashes']
        with store.connect() as conn:
            rows = conn.execute('SELECT count(*) AS n FROM canonical_crash WHERE batch_id=%s', (result['batch_id'],)).fetchone()['n']
        assert rows == independent['rows']
        response = client.get('/query', params={'source_id': result['source_id'], 'release_id': result['release_id'],
                                               'from': '2015-01-01', 'to': '2026-12-31'})
        response.raise_for_status()
        save(output / 'query.json', response.json())
        save(output / 'query-verification.json', verify_query(response.json(), independent))
        from acceptance_web import verify as verify_web
        measured('website_service', lambda: verify_web(output, result, independent))
        replays=[]
        for label, filename in [('same_name',original['name']),('renamed','renamed-identical'+Path(original['name']).suffix)]:
            second, work = new_job(filename)
            ready = measured(label+'_recipe_sample_full_QA', lambda: agent.agent_process(second['files'], work, second['options'],
                                              lambda *a, **kw: None, lambda: None, job=second))
            assert ready is not None
            measured(label+'_publication', lambda: worker.publish(second, ready, lambda: None))
            replay = store.get_job(second['id'])
            save(output / (label+'-replay.json'), agent.safe(replay))
            assert replay['status'] == 'no_change' and replay['release_id'] == result['release_id']
            replays.append({'kind':label,'status':replay['status'],'job_id':str(second['id'])})
        with store.connect() as conn:
            assert conn.execute('SELECT count(*) AS n FROM canonical_crash').fetchone()['n']==independent['rows']
            usage=conn.execute('SELECT model_calls,tool_calls FROM agent_sessions ORDER BY created_at').fetchall()
        assert all(row['model_calls']==0 for row in usage)
        assert digest(source) == original['sha256']
        save(output / 'acceptance.json', {'status': 'passed', 'model_calls': 0, 'elapsed_seconds': time.monotonic() - start,
            'timings': timings, 'usage':usage,'replays':replays,'independent_rows': rows, 'release_id': result['release_id'], 'replay_status': replay['status'],
            'limits': ['Deterministic replay of reviewed contract, not autonomous model discovery.',
                       'No actual browser upload or positional accuracy certification.',
                       'Remaining P0 matrix and dependent adapters are separate acceptance gates.']})
    except BaseException as exc:
        # Do not serialize credentials or database driver tracebacks.
        save(output / 'failure.json', {'type': type(exc).__name__, 'message': str(exc).replace(password, '[redacted]'),
                                       'details':agent.safe(getattr(exc,'details',{})),
                                       'timings': timings, 'elapsed_seconds': time.monotonic() - start})
        print('Acceptance failed:', type(exc).__name__, '; see preserved failure.json', flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--storage-policy', required=True, choices=['recent-two','keep-full'])
    parser.add_argument('--proof', required=True, type=Path)
    parser.add_argument('--dataset',choices=['act','tas'],default='act',help='Select independent oracle; this is reviewed replay, not blind discovery')
    parser.add_argument('--executor-image', required=True)
    parser.add_argument('--owned-child',action='store_true',help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if not arguments.owned_child:
        if arguments.output.exists():parser.error('Use a fresh owned output directory')
        from managed_acceptance import launch
        raise SystemExit(launch(arguments,suite=arguments.dataset.upper()+'-offline-acceptance'))
    run(arguments)
