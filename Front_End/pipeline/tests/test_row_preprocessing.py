"""Literal duplicate oracle and hostile adapter output; no shared expected projector."""
import hashlib
import json
from pathlib import Path
import pytest

from test_limited_geography import source_fixture
from arsia_pipeline import config
from arsia_pipeline.adapter_reuse import ADAPTER
from arsia_pipeline.errors import ValidationFailure
from arsia_pipeline.isolated_executor import run_python
from arsia_pipeline.row_preprocessing import PLAN, enabled
from arsia_pipeline.trusted_qa import validate_candidate


def fixture(root, conflict=False):
    contract,files=source_fixture(root)
    contract['resources'][0]['preprocessing']=dict(PLAN)
    path=Path(files[0]['path'])
    path.write_text('ID,DATE,Event_X,Event_Y,Note\n'
                    '001,2024-01-01,123,456,First\n'
                    '002,2024-02-01,,,Second\n'
                    '001,2024-01-01,123,456,'+('Conflict' if conflict else 'First')+'\n'
                    '002,2024-02-01,,,Second\n')
    files[0].update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size=path.stat().st_size)
    from source_binding_fixture import add_reference
    add_reference(files,root)
    return contract,files


def execute(root, contract, files, code=ADAPTER, mode='full'):
    return run_python(code,files,root/'runs',source_contract=contract,mode=mode,
                      limits={'seconds':15,'memory_mb':128})


@pytest.mark.parametrize('mode',['sample','full'])
def test_all_original_rows_have_literal_destinations_and_counts(tmp_path,monkeypatch,mode):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=fixture(tmp_path)
    run=execute(tmp_path,c,files,mode=mode)
    assert run['status']=='succeeded',run
    result=validate_candidate(run,c,files,run['code_sha256'],tmp_path,operation_policy=True)
    output=Path(run['output_dir'])
    rows=[json.loads(line) for line in (output/'crashes.jsonl').read_text().splitlines()]
    ledger=[json.loads(line) for line in (output/'row-lineage.jsonl').read_text().splitlines()]
    # Private literal oracle. IDs, row destinations and actual raw values are not
    # generated with canonical.project, SDK or preprocessing helpers.
    assert [(r['raw_key'],r['occurrence_date'],r['row_locator'],r['extensions']['Note']) for r in rows]==[
        (['001'],'2024-01-01','csv:1','First'),(['002'],'2024-02-01','csv:2','Second')]
    assert [(r['row_locator'],r['destination_locator'],r['count_allocation'],r['disposition']) for r in ledger]==[
        ('csv:1','csv:1',1,'retained'),('csv:2','csv:2',1,'retained'),
        ('csv:3','csv:1',0,'exact_duplicate'),('csv:4','csv:2',0,'exact_duplicate')]
    assert result['summary']['crash_count']==2
    assert result['summary']['raw_record_count']==4
    assert result['summary']['collapsed_duplicate_record_count']==2
    assert result['summary']['fatalities'] is None
    assert result['admission']['status']==('admitted' if mode=='full' else 'sample_only')
    assert result['admission']['artifact_hashes']['row-lineage.jsonl']==hashlib.sha256((output/'row-lineage.jsonl').read_bytes()).hexdigest()


@pytest.mark.parametrize('mutation',[
    'entries.pop()',
    'entries[-1]["count_allocation"]=1',
    'entries[-1]["destination_locator"]="csv:1"',
    'entries.append(entries[0])',
    'entries[-1]["raw_sha256"]="0"*64',
])
def test_forged_or_missing_destination_ledger_fails_independent_qa(tmp_path,monkeypatch,mutation):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=fixture(tmp_path)
    code=ADAPTER+'\n    import json\n    ctx.lineage.flush()\n    ctx.lineage.seek(0)\n    entries=[json.loads(v) for v in (ctx.output_dir/"row-lineage.jsonl").read_text().splitlines()]\n    '+mutation+'\n    ctx.lineage.seek(0)\n    ctx.lineage.truncate()\n    ctx.lineage.write("".join(json.dumps(v)+"\\n" for v in entries))\n'
    run=execute(tmp_path,c,files,code)
    assert run['status']=='succeeded',run
    with pytest.raises(ValidationFailure,match='destination|conservation'):
        validate_candidate(run,c,files,run['code_sha256'],tmp_path)


def test_silent_canonical_deletion_is_not_authorized_by_a_valid_ledger(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=fixture(tmp_path)
    code=ADAPTER.replace("ctx.emit(resource['grain'], ctx.project(role, locator, row))",
                         "if row['ID']=='001':ctx.emit(resource['grain'], ctx.project(role, locator, row))")
    run=execute(tmp_path,c,files,code)
    assert run['status']=='succeeded'
    with pytest.raises(ValidationFailure,match='conservation'):
        validate_candidate(run,c,files,run['code_sha256'],tmp_path)


def test_conflicting_raw_values_cannot_be_selected_or_ignored(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=fixture(tmp_path,conflict=True)
    run=execute(tmp_path,c,files)
    assert run['status']=='failed'
    # Malicious adapter emits no rows and forges an empty ledger; host still
    # scans every raw row and finds the actual same-key value conflict first.
    run=execute(tmp_path,c,files,'def adapt(ctx):\n    pass\n')
    assert run['status']=='succeeded'
    with pytest.raises(ValidationFailure,match='Conflicting raw values'):
        validate_candidate(run,c,files,run['code_sha256'],tmp_path)


@pytest.mark.parametrize('change',[{'equality':'key_only'},{'count_policy':'sum'},{'operation':'drop_invalid'}])
def test_unreviewed_preprocessing_plan_is_not_ignored(change):
    with pytest.raises(ValidationFailure):enabled({'preprocessing':{**PLAN,**change}})
