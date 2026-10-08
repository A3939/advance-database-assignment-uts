"""Real Docker isolation tests; skips explicitly if its dedicated image is absent."""
import json
from pathlib import Path

import pytest

from arsia_pipeline.isolated_executor import IMAGE, arguments, bounded_report, docker, run_python


@pytest.mark.parametrize('mode', ['sample', 'full'])
@pytest.mark.parametrize('fault', [None, 'duplicate_parent', 'unmatched_child', 'fabricated_count', 'broadcast_count'])
def test_real_provisional_lookup_preserves_rows_and_cannot_gain_admission(tmp_path, fault, mode):
    import hashlib
    from test_lookup_projection import bundle
    from arsia_pipeline.errors import NeedsInput, UnsupportedCapability, ValidationFailure
    from arsia_pipeline.trusted_qa import validate_candidate
    if docker(['image', 'inspect', IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    c, files = bundle(tmp_path)
    c['resources'][0]['source_url'] = 'https://cdn.example/events.csv'
    c['lookup_tables'][0]['source_url'] = 'https://cdn.example/codes.csv'
    if fault in {'duplicate_parent', 'unmatched_child', 'broadcast_count'}:
        file = files[1] if fault == 'duplicate_parent' else files[0]
        path = Path(file['path'])
        if fault == 'duplicate_parent':
            path.write_text(path.read_text() + 'A,U,0,149.3,-35.4\n')
        elif fault == 'unmatched_child':
            path.write_text(path.read_text().replace(',B,1', ',missing,1'))
        else:
            path.write_text(path.read_text().replace(',B,1', ',A,1'))
        file['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        file['size'] = path.stat().st_size
    code = 'def adapt(ctx):\n    for locator,raw in ctx.iter_rows("crash"):\n        ctx.emit("crash",ctx.project("crash",locator,raw))\n'
    if fault == 'fabricated_count':
        code = 'def adapt(ctx):\n    for locator,raw in ctx.iter_rows("crash"):\n        row=ctx.project("crash",locator,raw)\n        row["fatalities"]=999\n        ctx.emit("crash",row)\n'
    run = run_python(code, files, tmp_path / 'runs', source_contract=c, mode=mode, limits={'seconds': 20, 'memory_mb': 128})
    if fault in {'duplicate_parent', 'unmatched_child'}:
        assert run['status'] == 'failed', run
        return
    assert run['status'] == 'succeeded', run
    if fault == 'broadcast_count':
        # The sandbox can faithfully project both rows while duplicating one
        # physical parent's population. Independent host allocation QA rejects
        # it before any replay-success/admission receipt is issued.
        with pytest.raises(ValidationFailure) as exc:
            validate_candidate(run, c, files, run['code_sha256'], tmp_path)
        assert exc.value.qa[0]['code'] == 'LOOKUP_COUNT_BROADCAST'
        assert not list(tmp_path.glob('trusted-lookup-replay-*.json'))
        return
    if fault == 'fabricated_count':
        with pytest.raises(ValidationFailure, match='independent raw-row projection'):
            validate_candidate(run, c, files, run['code_sha256'], tmp_path)
        assert not list(tmp_path.glob('trusted-lookup-replay-*.json'))
        return
    rows = [json.loads(line) for line in (Path(run['output_dir']) / 'crashes.jsonl').read_text().splitlines()]
    assert len(rows) == 2
    assert [r['raw_key'] for r in rows] == [['001'], ['002']]
    assert [r['casualties'] for r in rows] == [5, 1]
    assert [r['coordinates'] for r in rows] == [[149.1, -35.2], [149.2, -35.3]]
    assert all(r['lookup_lineage']['code']['parent']['file_sha256'] == files[1]['sha256'] for r in rows)
    with pytest.raises(NeedsInput) as exc:
        validate_candidate(run, c, files, run['code_sha256'], tmp_path)
    assert exc.value.code == 'evidence_needed'
    assert exc.value.details['lookup_replay']['row_equality_verified'] is True
    assert exc.value.details['lookup_replay']['parent_rows'] == {'codes': 2}
    assert exc.value.details['lookup_replay']['mode'] == mode


def test_container_has_only_task_mounts_and_no_authority():
    command = arguments('owned', '/task/input', '/task/output', 'sha256:test',
        {'memory_mb': 64, 'cpus': 1, 'pids': 32, 'output_bytes': 1024})
    for required in ['--network=none', '--read-only', '--user=65534:65534', '--cap-drop=ALL',
                     '--security-opt=no-new-privileges', '--pids-limit=32']:
        assert required in command
    mounts = [command[i+1] for i, value in enumerate(command) if value == '--mount']
    assert mounts == ['type=bind,source=/task/input,target=/input,readonly',
                      'type=bind,source=/task/output,target=/output']
    assert '--env' not in command and '-e' not in command
    assert not any('docker.sock' in part for part in command)


@pytest.mark.parametrize('mode',['sample','full'])
def test_real_lookup_executor_and_semantic_qa_with_scoped_receipts(tmp_path,monkeypatch,mode):
    from arsia_pipeline import config
    from arsia_pipeline.trusted_qa import validate_candidate
    from test_lookup_projection import bundle
    from test_lookup_admission import configure_admissible, CODE
    if docker(['image','inspect',IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=bundle(tmp_path)
    configure_admissible(c,files,tmp_path/'evidence')
    run=run_python(CODE,files,tmp_path/'runs',source_contract=c,mode=mode,limits={'seconds':20,'memory_mb':128})
    assert run['status']=='succeeded',run
    result=validate_candidate(run,c,files,run['code_sha256'],tmp_path)
    assert result['admission']['status']==('admitted' if mode=='full' else 'sample_only')
    assert (result['summary']['crash_count'],result['summary']['fatalities'],result['summary']['casualties'])==(2,2,6)
    assert result['admission']['evidence']['transform_plans']['executor_image']==run['image']


def test_runner_envelope_cannot_return_person_rows_as_error_or_telemetry():
    report=bounded_report({'status':'failed','error':{'type':'KeyError','message':'PERSON-ROW',
        'frames':[{'file':'PERSON-ROW','function':'PERSON-ROW','line':12}]},
        'usage':{'secret':'PERSON-ROW','seconds':float('inf'),'ru_maxrss_bytes':23}},
        {'seconds':10,'memory_mb':64})
    assert 'PERSON-ROW' not in json.dumps(report)
    assert report['error']['type']=='KeyError'
    assert report['usage']=={'ru_maxrss_bytes':23}


@pytest.mark.parametrize('forge_operation', [False, True])
def test_real_coordinate_plan_receipt_and_forged_operation_are_checked(tmp_path, forge_operation):
    from test_canonical_v2 import contract
    from arsia_pipeline.trusted_qa import validate_candidate
    from arsia_pipeline.errors import ValidationFailure
    from arsia_pipeline.transform_plan import plan
    import hashlib
    if docker(['image','inspect',IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    source=tmp_path/'source.csv'
    source.write_text('ID,DATE,SEVERITY,DEATHS,INJURED,X,Y\n001,30/04/2024 13:20,F,2,3,149.1,-35.2\n')
    file={'id':'file1','name':source.name,'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'size':source.stat().st_size}
    c=contract()
    c['resources'][0]['mapping']['geography']={'x_field':'X','y_field':'Y','crs':'EPSG:4326'}
    c['evidence']['geography']=[{'document_id':'synthetic','quote':'Synthetic canonical sample test only; not source admission.'}]
    code='def adapt(ctx):\n    for locator,raw in ctx.iter_rows("crash"):\n        row=ctx.project("crash",locator,raw)\n'
    if forge_operation:code+='        row["transform_operation_sha256"]="f"*64\n'
    code+='        ctx.emit("crash",row)\n'
    run=run_python(code,[file],tmp_path/'runs',source_contract=c,limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded',run
    assert run['transform_probe_image']==run['image']
    assert run['transform_plans']['crash']['operation_sha256']==plan('EPSG:4326')['operation_sha256']
    if forge_operation:
        with pytest.raises(ValidationFailure,match='independent raw-row projection'):
            validate_candidate(run,c,[file],run['code_sha256'],tmp_path)
    else:
        result=validate_candidate(run,c,[file],run['code_sha256'],tmp_path)
        assert result['admission']['status']=='sample_only'
        assert result['admission']['evidence']['transform_plans']['executor_image']==run['image']


@pytest.fixture
def executable(tmp_path):
    try:
        available = docker(['image', 'inspect', IMAGE])
    except (FileNotFoundError, OSError):
        pytest.skip('Docker unavailable; real isolation not verified')
    if available.returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    source = tmp_path/'source.csv'
    source.write_text('id,value\n1,2\n')
    files = [{'id': 'file', 'file_id': 'file', 'name': source.name, 'path': str(source)}]
    def execute(code, **limits):
        result = run_python(code, files, tmp_path/'runs', source_contract={'resources': []},
            limits={'seconds': 15, 'memory_mb': 128, **limits})
        assert source.read_text() == 'id,value\n1,2\n'
        name = 'arsia-adapter-'+result['run_id']
        assert docker(['inspect', name]).returncode != 0
        persisted = Path(result['output_dir']).parent/'execution.json'
        assert json.loads(persisted.read_text())['status'] == result['status']
        return result
    return execute


def test_actual_container_file_network_and_secret_boundaries(executable):
    result = executable('''
def adapt(ctx):
    import os, socket
    from pathlib import Path
    assert not Path('/var/run/docker.sock').exists()
    assert not Path('/Users/zhengpeixian').exists()
    assert not os.environ.get('OPENAI_API_KEY')
    assert not os.environ.get('PGPASSWORD')
    try:
        Path('/input/file-0.csv').write_text('mutated')
    except OSError:
        pass
    else:
        raise AssertionError('Input was writable')
    try:
        Path('/opt/arsia/probe').write_text('mutated')
    except OSError:
        pass
    else:
        raise AssertionError('Root filesystem was writable')
    try:
        socket.create_connection(('1.1.1.1', 443), timeout=1).close()
    except OSError:
        pass
    else:
        raise AssertionError('Network egress succeeded')
''')
    assert result['status'] == 'succeeded', result
    assert result['usage']['ru_maxrss_bytes'] > 0


def test_timeout_is_diagnostic_and_cleans_owned_container(executable):
    result = executable('def adapt(ctx):\n    while True: pass\n', seconds=1)
    assert result['status'] == 'timeout', result
    assert result['error']['type'] == 'Timeout'


def test_memory_limit_is_diagnostic(executable):
    result = executable('def adapt(ctx):\n    data=[]\n    while True: data.append(bytearray(4*1024*1024))\n', memory_mb=64)
    assert result['status'] == 'oom', result


def test_output_symlink_is_refused(executable):
    result = executable("def adapt(ctx):\n    import os\n    os.symlink('/etc/passwd', '/output/forbidden')\n")
    assert result['status'] == 'failed', result
    assert 'symlink' in result['error']['message']


def test_runtime_error_is_structured_without_stdout(executable):
    result = executable('def adapt(ctx):\n    unknown_adapter_variable\n')
    assert result['status'] == 'failed', result
    assert result['error']['type'] == 'NameError'
    assert result['error']['frames']
    assert result['stdout'] == result['stderr'] == ''


def test_task_storage_limit_counts_prior_runs_without_removing_evidence(tmp_path):
    from arsia_pipeline.isolated_executor import check_storage
    old = tmp_path/'prior-run'
    old.mkdir()
    (old/'evidence').write_bytes(b'x'*50)
    with pytest.raises(RuntimeError, match='Task storage budget'):
        check_storage(tmp_path, {'work_bytes':100,'reserve_bytes':0}, incoming=51)
    assert (old/'evidence').read_bytes() == b'x'*50


def test_disk_reserve_prevents_another_execution(tmp_path, monkeypatch):
    from arsia_pipeline import isolated_executor
    from collections import namedtuple
    usage = namedtuple('usage', 'total used free')
    monkeypatch.setattr(isolated_executor.shutil, 'disk_usage', lambda *_:usage(100,90,10))
    with pytest.raises(RuntimeError, match='free disk reserve'):
        isolated_executor.check_storage(tmp_path, {'work_bytes':100,'reserve_bytes':8}, incoming=3)


@pytest.mark.parametrize('case', ['admitted', 'missing_definition', 'duplicate', 'overflow'])
def test_real_count_arithmetic_and_full_semantic_gate(tmp_path, monkeypatch, case):
    """Synthetic publisher receipts test the full gate, not real-source admission."""
    import hashlib
    from test_count_semantics import fixture, DOC
    from arsia_pipeline import config
    from arsia_pipeline.errors import NeedsInput
    from arsia_pipeline.trusted_qa import validate_candidate
    if docker(['image', 'inspect', IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    statement = 'Documented fields only' if case == 'missing_definition' else 'Total casualties = deaths + injured'
    c, docs, accepted = fixture(statement)
    c.update(contract_version='canonical-v2', update={'mode': 'snapshot'}, evidence=accepted)
    c['source'].update(source_id='count_operation_fixture', jurisdiction=['SA'], publisher='Synthetic publisher',
                       title='Synthetic count semantics fixture', licence='Synthetic test only', grain='crash',
                       coverage={'from': '2024-01-01', 'to': '2024-12-31'})
    c['resources'][0]['mapping']['date']={'field':'date','formats':['%Y-%m-%d']}
    if case == 'duplicate':
        c['resources'][0]['mapping']['casualties']['sum_fields'] = ['deaths', 'deaths']
    doc = docs['official']; sha = doc['sha256']
    (tmp_path / 'sha256').mkdir(); (tmp_path / 'sha256' / sha).write_bytes(doc['content_bytes'])
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'status': 'fetched', 'sha256': sha, 'final_url': DOC, 'final_host_official': True}))
    c['documents'] = [{'document_id': 'official', 'receipt_path': str(receipt)}]
    source = tmp_path / 'source.csv'
    source.write_text('id,date,deaths,injured\n001,2024-04-30,' + ('2147483647,1' if case == 'overflow' else '2,3') + '\n')
    file = {'id': 'upload', 'name': source.name, 'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'size': source.stat().st_size}
    files=[file]
    from source_binding_fixture import add_reference
    add_reference(files,tmp_path,'https://data.example.gov.au/api/views/abcd-1234/rows.csv?accessType=DOWNLOAD')
    code = 'def adapt(ctx):\n    for locator,raw in ctx.iter_rows("crash"):\n        ctx.emit("crash",ctx.project("crash",locator,raw))\n'
    run = run_python(code, files, tmp_path / 'runs', mode='full', source_contract=c, limits={'seconds': 15, 'memory_mb': 128})
    if case in {'duplicate', 'overflow'}:
        assert run['status'] == 'failed' and run['error']['type'] == 'ContractError'
    elif case == 'missing_definition':
        assert run['status'] == 'succeeded'
        with pytest.raises(NeedsInput) as failure:
            validate_candidate(run, c, files, run['code_sha256'], tmp_path)
        assert failure.value.details['count_operation_review']['issues'][0]['code'] == 'COUNT_SUM_UNGROUNDED'
    else:
        assert run['status'] == 'succeeded', run
        result = validate_candidate(run, c, files, run['code_sha256'], tmp_path)
        assert result['summary']['casualties'] == 5
        assert result['admission']['status'] == 'admitted'
        assert result['admission']['evidence']['count_operation_review']['decisions'][0]['metric'] == 'casualties'


@pytest.mark.parametrize('case', ['admitted', 'wrong_outcome', 'merged_categories'])
def test_real_category_output_requires_independent_semantic_admission(tmp_path, monkeypatch, case):
    """Synthetic renderer evidence exercises a real container and full QA."""
    import hashlib
    from test_category_evidence import fixture, URL
    from arsia_pipeline import config
    from arsia_pipeline.errors import NeedsInput
    from arsia_pipeline.trusted_qa import validate_candidate
    if docker(['image', 'inspect', IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    c, metadata = fixture()
    metadata['fields'][0]['type']='esriFieldTypeOID';metadata['objectIdField']='ID';metadata['maxRecordCount']=100
    metadata['fields'][1]['type']='esriFieldTypeDate';metadata['dateFieldsTimeReference']={'timeZoneIANA':'UTC','timeZone':'UTC'}
    raw = json.dumps(metadata).encode(); sha = hashlib.sha256(raw).hexdigest()
    c.update(contract_version='canonical-v2', update={'mode': 'snapshot'})
    c['source'].update(source_id='category_fixture', jurisdiction=['TAS'], publisher='Synthetic publisher',
                       title='Synthetic classification fixture', licence='Synthetic test only', grain='crash',
                       coverage={'from': '2024-01-01', 'to': '2024-12-31'})
    c['resources'][0]['file_id'] = 'upload'
    c['resources'][0]['mapping']['date']={'field':'DATE','kind':'epoch_ms','timezone':'UTC'}
    categories = c['resources'][0]['mapping']['severity']['categories']
    if case == 'wrong_outcome': categories['P']['is_fatal_crash'] = True
    if case == 'merged_categories': categories['P']['code'] = 'fatal'
    c['evidence'] = {claim: [{'document_id': 'official', 'quote': raw.decode()}]
                     for claim in ('source_identity', 'grain', 'date', 'severity', 'coverage_update')}
    (tmp_path / 'sha256').mkdir(); (tmp_path / 'sha256' / sha).write_bytes(raw)
    receipt = tmp_path / 'receipt.json'
    receipt.write_text(json.dumps({'status': 'fetched', 'sha256': sha, 'final_url': URL + '?f=pjson', 'final_host_official': True}))
    c['documents'] = [{'document_id': 'official', 'receipt_path': str(receipt)}]
    # Full QA needs a hash-bound representation, independently of category evidence.
    # These are synthetic protocol receipts, never an official source acceptance.
    query_url=URL+'/query?where=1%3D1&outFields=*&returnGeometry=false&f=json'
    source = tmp_path / 'source.json'
    source.write_text(json.dumps({'objectIdFieldName':'ID','features':[
        {'attributes':{'ID':i,'DATE':1714435200000,'SEVERITY':severity}}
        for i,severity in enumerate(['F','P','U'],1)]}))
    data_sha=hashlib.sha256(source.read_bytes()).hexdigest()
    (tmp_path/'sha256'/data_sha).write_bytes(source.read_bytes())
    query_receipt=tmp_path/'query.receipt.json'
    query_receipt.write_text(json.dumps({'status':'fetched','sha256':data_sha,'final_url':query_url,'final_host_official':True}))
    c['documents'].append({'document_id':'query','receipt_path':str(query_receipt)})
    c['resources'][0]['source_url']=query_url
    c['resources'][0]['table']={'format':'json','json_kind':'arcgis'}
    file = {'id': 'upload', 'name': source.name, 'path': str(source), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'size': source.stat().st_size}
    code = 'def adapt(ctx):\n    for locator,raw in ctx.iter_rows("crash"):\n        ctx.emit("crash",ctx.project("crash",locator,raw))\n'
    run = run_python(code, [file], tmp_path / 'runs', mode='full', source_contract=c, limits={'seconds': 15, 'memory_mb': 128})
    assert run['status'] == 'succeeded', run
    if case == 'admitted':
        result = validate_candidate(run, c, [file], run['code_sha256'], tmp_path)
        assert result['admission']['status'] == 'admitted'
        assert result['summary']['crash_count'] == 3
        # The unknown source category prevents a complete fatal-total claim.
        assert result['summary']['fatal_crash_count'] is None
        rows = [json.loads(line) for line in (Path(run['output_dir']) / 'crashes.jsonl').read_text().splitlines()]
        assert [row['is_fatal_crash'] for row in rows] == [True, False, None]
        review = result['admission']['evidence']['category_review']
        assert review['ok'] and len(review['decisions']) == 3
        assert next(item for item in review['decisions'] if item['source_code'] == 'U')['fatal_flag'] is None
    else:
        with pytest.raises(NeedsInput) as failure:
            validate_candidate(run, c, [file], run['code_sha256'], tmp_path)
        expected = 'CATEGORY_OUTCOME_CONFLICT' if case == 'wrong_outcome' else 'CATEGORY_CODE_COLLISION'
        assert expected in {item['code'] for item in failure.value.details['category_review']['issues']}


def test_real_full_qa_derives_complete_source_membership_from_exact_export(tmp_path, monkeypatch):
    from test_source_completeness import export, URL
    from arsia_pipeline import config
    from arsia_pipeline.trusted_qa import validate_candidate
    if docker(['image', 'inspect', IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    result, file = export(tmp_path, for_admission=True)
    receipt = json.loads(Path(file['receipt_path']).read_text())
    metadata = receipt['requests']['metadata']
    raw = (Path(file['receipt_path']).parent / 'sha256' / metadata['sha256']).read_text()
    meta_receipt = Path(file['receipt_path']).parent / 'synthetic-metadata.json'
    meta_receipt.write_text(json.dumps({**metadata, 'status': 'fetched', 'final_host_official': True}))
    c = {'contract_version': 'canonical-v2', 'source': {'source_id': 'complete_export_fixture', 'jurisdiction': ['ACT'],
         'publisher': 'Synthetic publisher', 'title': 'Synthetic ArcGIS layer', 'licence': 'Synthetic test only', 'grain': 'crash',
         'dataset_url': URL, 'coverage': {'from': '2024-01-01', 'to': '2024-12-31'}}, 'update': {'mode': 'snapshot'},
         'resources': [{'role': 'crash', 'file_id': file['id'], 'grain': 'crash', 'key': ['ID'], 'mapping': {
             'date': {'field': 'DATE', 'formats': ['%Y-%m-%d']},
             'severity': {'field': 'SEVERITY', 'categories': {'Minor': {'code': 'minor', 'label': 'Minor injury', 'is_fatal_crash': False}}},
             'geography': {'x_field': '__geometry_x', 'y_field': '__geometry_y', 'crs': 'EPSG:4326'}}}],
         'documents': [{'document_id': 'metadata', 'receipt_path': str(meta_receipt)}],
         'evidence': {claim: [{'document_id': 'metadata', 'quote': raw}] for claim in ('source_identity', 'grain', 'date', 'severity', 'coverage_update', 'geography')}}
    code = 'def adapt(ctx):\n    for locator,raw in ctx.iter_rows("crash"):\n        ctx.emit("crash",ctx.project("crash",locator,raw))\n'
    run = run_python(code, [file], tmp_path / 'runs', mode='full', source_contract=c, limits={'seconds': 15, 'memory_mb': 128})
    assert run['status'] == 'succeeded', run
    admitted = validate_candidate(run, c, [file], run['code_sha256'], tmp_path)
    proof, = admitted['admission']['evidence']['source_completeness']['resources']
    assert proof['status'] == 'verified' and proof['record_count'] == 3
    assert proof['input_sha256'] == file['sha256']
    assert admitted['summary']['crash_count'] == 3


@pytest.mark.parametrize('case', ['complete', 'mismatched_count', 'negated'])
def test_real_casualty_scope_evidence_and_full_reconciliation(tmp_path, monkeypatch, case):
    from test_casualty_review import structured_scope
    from arsia_pipeline.trusted_qa import validate_candidate
    from arsia_pipeline.errors import NeedsInput, ValidationFailure
    if docker(['image', 'inspect', IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    declaration = ('This is not a complete casualty register identified by EVENT_ID and PERSON_NO.'
                   if case == 'negated' else None)
    c, files, _ = structured_scope(tmp_path, monkeypatch, total=2 if case == 'mismatched_count' else 1,
                                   declaration=declaration)
    code = ('def adapt(ctx):\n'
            '    for role, grain in [("crash", "crash"), ("people", "casualty")]:\n'
            '        for locator, raw in ctx.iter_rows(role):\n'
            '            ctx.emit(grain, ctx.project(role, locator, raw))\n')
    run = run_python(code, files, tmp_path / 'runs', source_contract=c, mode='full',
                     limits={'seconds': 15, 'memory_mb': 128})
    assert run['status'] == 'succeeded', run
    if case == 'negated':
        with pytest.raises(NeedsInput) as failure:
            validate_candidate(run, c, files, run['code_sha256'], tmp_path)
        assert failure.value.details['casualty_scope_review']['issues'][0]['code'] == 'CASUALTY_SCOPE_REQUIRED'
    elif case == 'mismatched_count':
        with pytest.raises(ValidationFailure, match='Complete casualty register'):
            validate_candidate(run, c, files, run['code_sha256'], tmp_path)
    else:
        result = validate_candidate(run, c, files, run['code_sha256'], tmp_path)
        assert result['admission']['status'] == 'admitted'
        assert result['summary']['casualties'] == 1
        assert result['admission']['evidence']['casualty_scope_review']['decisions'][0]['complete'] is True


@pytest.mark.parametrize('case', ['valid', 'wrong_measure', 'single_sum_bypass'])
def test_real_direct_count_meaning_gate(tmp_path, monkeypatch, case):
    import hashlib
    from test_count_definitions import direct
    from test_count_semantics import DOC
    from arsia_pipeline import config
    from arsia_pipeline.errors import NeedsInput
    from arsia_pipeline.trusted_qa import validate_candidate
    if docker(['image', 'inspect', IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    c, docs, accepted=direct('fatalities', 'deaths' if case=='valid' else 'injured')
    if case=='single_sum_bypass':c['resources'][0]['mapping']['fatalities']={'sum_fields':['injured']}
    c.update(contract_version='canonical-v2',update={'mode':'snapshot'})
    c['source'].update(source_id='direct_count_fixture',publisher='Synthetic publisher',title='Synthetic direct count',licence='Fixture',jurisdiction=['ACT'],coverage={'from':'2024-01-01','to':'2024-12-31'})
    c['resources'][0]['table']={'format':'csv'};c['resources'][0]['mapping']['date']['formats']=['%Y-%m-%d']
    source=tmp_path/'data.csv';source.write_text('id,date,deaths,injured,total\n1,2024-01-01,2,3,5\n')
    files=[{'id':'upload','name':source.name,'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'size':source.stat().st_size}]
    doc=docs['official'];(tmp_path/'sha256').mkdir();(tmp_path/'sha256'/doc['sha256']).write_bytes(doc['content_bytes'])
    receipt=tmp_path/'receipt.json';receipt.write_text(json.dumps({'status':'fetched','sha256':doc['sha256'],'final_url':DOC,'final_host_official':True}))
    c['documents']=[{'document_id':'official','receipt_path':str(receipt)}];c['evidence']=accepted
    from source_binding_fixture import add_reference
    add_reference(files,tmp_path,'https://data.example.gov.au/api/views/abcd-1234/rows.csv?accessType=DOWNLOAD')
    code='def adapt(ctx):\n    for locator, raw in ctx.iter_rows("crash"):\n        ctx.emit("crash", ctx.project("crash", locator, raw))\n'
    run=run_python(code,files,tmp_path/'runs',source_contract=c,mode='full',limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded',run
    if case=='valid':
        result=validate_candidate(run,c,files,run['code_sha256'],tmp_path)
        assert result['admission']['status']=='admitted' and result['summary']['fatalities']==2
    else:
        with pytest.raises(NeedsInput) as failure:validate_candidate(run,c,files,run['code_sha256'],tmp_path)
        assert failure.value.details['count_operation_review']['issues'][0]['code']=='COUNT_MEANING_CONFLICT'


@pytest.mark.parametrize('case', ['valid', 'omit_record', 'shift_locator', 'forged_plan'])
def test_real_workbook_plan_replayed_by_sdk_and_trusted_qa(tmp_path, case):
    from test_workbook_plan import workbook, file_for
    from test_canonical_v2 import contract
    from arsia_pipeline.intakereaders import detect_tables
    from arsia_pipeline.trusted_qa import validate_candidate
    from arsia_pipeline.errors import ValidationFailure
    if docker(['image', 'inspect', IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    book, file = workbook(tmp_path)
    # This fixture has two real rows. The separate reader regression verifies
    # internal blanks are conserved and cannot be dropped to pass QA.
    book.active.delete_rows(7)
    book.save(file['path'])
    file = file_for(Path(file['path']))
    c = contract()
    table = detect_tables(file)[0]
    c['resources'][0]['table'] = table
    if case == 'forged_plan':
        table['parser_plan']['header_row'] = 6
    code = 'def adapt(ctx):\n    for locator, raw in ctx.iter_rows("crash"):\n'
    if case == 'omit_record':
        code += '        if raw["ID"] == "002": continue\n'
    if case == 'shift_locator':
        code += '        locator = locator.replace("6]", "5]")\n'
    code += '        ctx.emit("crash", ctx.project("crash", locator, raw))\n'
    run = run_python(code, [file], tmp_path / 'runs', source_contract=c, mode='sample',
                     limits={'seconds': 15, 'memory_mb': 128})
    if case == 'forged_plan':
        assert run['status'] == 'failed', run
        return
    assert run['status'] == 'succeeded', run
    if case != 'valid':
        with pytest.raises(ValidationFailure):
            validate_candidate(run, c, [file], run['code_sha256'], tmp_path)
        return
    result = validate_candidate(run, c, [file], run['code_sha256'], tmp_path)
    assert result['admission']['status'] == 'sample_only'
    assert result['summary']['crash_count'] == 2
    assert result['admission']['evidence']['parser_plans']['crash'] == table['parser_plan']
    rows = [json.loads(line) for line in (Path(run['output_dir']) / 'crashes.jsonl').read_text().splitlines()]
    assert [row['row_locator'] for row in rows] == ['["Records",6]', '["Records",7]']


@pytest.mark.parametrize('case', ['dictionary', 'people', 'unmatched_field'])
def test_real_candidate_cannot_hide_unassigned_tables_behind_dictionary_headers(tmp_path, case):
    from test_canonical_v2 import envelope
    from test_table_classification import attachment
    from arsia_pipeline.trusted_qa import validate_candidate
    from arsia_pipeline.errors import ValidationFailure
    if docker(['image', 'inspect', IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    c, file, _ = envelope(tmp_path)
    body = {'dictionary':'field,description\nID,Identifier of each crash\n',
            'people':'name,description\nPerson,Private personal observation\n',
            'unmatched_field':'field,description\nPERSON_ID,Unclassified personal observation\n'}[case]
    other = attachment(tmp_path, body)
    files = [file, other]
    code = 'def adapt(ctx):\n    for locator, raw in ctx.iter_rows("crash"):\n        ctx.emit("crash",ctx.project("crash",locator,raw))\n'
    run = run_python(code, files, tmp_path/'real-runs', source_contract=c, mode='sample',
                     limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded',run
    if case!='dictionary':
        with pytest.raises(ValidationFailure,match='not assigned a grain'):
            validate_candidate(run,c,files,run['code_sha256'],tmp_path)
        return
    result=validate_candidate(run,c,files,run['code_sha256'],tmp_path)
    assert result['summary']['crash_count']==1
    classified=result['admission']['evidence']['table_classification']['tables']
    assert next(r for r in classified if r['purpose']=='dictionary')['row_count']==1


@pytest.mark.parametrize('case',['valid','duplicate_key','omit_partition','forged_locator'])
def test_real_union_sdk_and_independent_qa(tmp_path,case):
    from test_table_plan import bundle
    from arsia_pipeline.trusted_qa import validate_candidate
    from arsia_pipeline.errors import ValidationFailure
    if docker(['image','inspect',IMAGE]).returncode:
        pytest.skip('Dedicated adapter image absent; host fallback prohibited')
    c,files=bundle(tmp_path,duplicate_key=case=='duplicate_key',reordered=case=='valid')
    code='def adapt(ctx):\n    for locator,raw in ctx.iter_rows("crash"):\n'
    if case=='omit_partition':code+='        if raw["ID"]=="002": continue\n'
    if case=='forged_locator':code+='        locator="csv:1"\n'
    code+='        ctx.emit("crash",ctx.project("crash",locator,raw))\n'
    run=run_python(code,files,tmp_path/'runs',source_contract=c,mode='sample',limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded',run
    if case!='valid':
        with pytest.raises(ValidationFailure):validate_candidate(run,c,files,run['code_sha256'],tmp_path)
        return
    result=validate_candidate(run,c,files,run['code_sha256'],tmp_path)
    assert result['summary']['crash_count']==2
    assert result['admission']['evidence']['parser_plans']['crash']['union_plan']['version']=='homogeneous-union-v1'
