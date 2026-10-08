"""An unresolved auxiliary cannot contaminate independently verified crash facts."""
import hashlib
import json
from pathlib import Path
import pytest

from test_limited_geography import source_fixture
from arsia_pipeline import config
from arsia_pipeline.adapter_reuse import ADAPTER
from arsia_pipeline.errors import ValidationFailure
from arsia_pipeline.isolated_executor import run_python
from arsia_pipeline.trusted_qa import validate_candidate, validate_contract


REASON='Unit identities conflict; linkage and unit counts remain unresolved.'


def fixture(root):
    contract,files=source_fixture(root)
    path=root/'unresolved-units.csv'
    path.write_text('CrashID,UnitID,Vehicle\n999,U01,Car\n999,U01,Truck\n')
    files.insert(1,{'id':'units','name':path.name,'path':str(path),'size':path.stat().st_size,
                  'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    contract['retained_resources']=[{'role':'units','grain':'unit','file_id':'units','table':{'format':'csv'},
        'reason':REASON,'requested':True}]
    return contract,files


def test_conflicting_auxiliary_is_retained_with_no_relationship_or_count_contribution(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=fixture(tmp_path)
    run=run_python(ADAPTER,files,tmp_path/'runs',source_contract=c,mode='full',limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded',run
    result=validate_candidate(run,c,files,run['code_sha256'],tmp_path)
    rows=[json.loads(line) for line in (Path(run['output_dir'])/'crashes.jsonl').read_text().splitlines()]
    assert len(rows)==1 and rows[0]['raw_key']==['001']
    assert result['summary']['crash_count']==1
    assert result['summary']['raw_record_count']==3
    assert result['summary']['retained_unverified_record_count']==2
    assert result['summary']['unit_count'] is None
    assert not (Path(run['output_dir'])/'units.jsonl').read_bytes()
    assert result['capabilities']['units'] is False
    limit=next(item for item in result['capability_limits'] if item['capability']=='units')
    assert limit['requested'] and not limit['target_satisfied'] and limit['reason']==REASON
    receipt=result['admission']['evidence']['retained_resources']['resources'][0]
    assert receipt['records_scanned']==2 and receipt['scan_complete'] is True
    assert receipt['semantic_qa']=='not_passed' and receipt['file_sha256']==files[1]['sha256']
    assert Path(files[1]['path']).read_text()=='CrashID,UnitID,Vehicle\n999,U01,Car\n999,U01,Truck\n'


@pytest.mark.parametrize('violation',['derived_relation','same_grain_facts','omit_declaration','missing_file','missing_reason'])
def test_unresolved_dependency_cannot_claim_verified_facts(tmp_path,violation):
    c,files=fixture(tmp_path)
    if violation=='derived_relation':c['relations']=[{'child':'units','parent':'events','fields':['CrashID']}]
    elif violation=='same_grain_facts':c['resources'].append({'role':'also_units','grain':'unit','file_id':'units','key':['UnitID'],'mapping':{},'table':{'format':'csv'}})
    elif violation=='omit_declaration':c.pop('retained_resources')
    elif violation=='missing_file':c['retained_resources'][0]['file_id']='unadmitted'
    else:c['retained_resources'][0].pop('reason')
    with pytest.raises(ValidationFailure):validate_contract(c,files)


def test_adapter_cannot_emit_unverified_auxiliary_rows(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=fixture(tmp_path)
    code=ADAPTER+'\n    ctx.emit("unit",{"resource_role":"units","row_locator":"csv:1","record_id":"U01"})\n'
    run=run_python(code,files,tmp_path/'runs',source_contract=c,mode='full',limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded'
    with pytest.raises(ValidationFailure,match='wrong source grain'):
        validate_candidate(run,c,files,run['code_sha256'],tmp_path)
